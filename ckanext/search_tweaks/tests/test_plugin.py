import pytest

import ckan.plugins as p
import ckan.lib.search.query as query

from ckanext.search_tweaks import CONFIG_PREFER_BOOST
import ckanext.search_tweaks.plugin as plugin


MOLECULE_FQ = "+dataset_type:molecule"


@pytest.fixture
def before_search(monkeypatch, ckan_config):
    """Run the hook without requiring a live Solr package search."""
    monkeypatch.setattr(plugin, "boost_preffered", lambda: True)
    monkeypatch.setattr(
        plugin.plugins, "PluginImplementations", lambda interface: []
    )

    def run(**search_params):
        return plugin.SearchTweaksPlugin.before_search(object(), search_params)

    return run


@pytest.mark.usefixtures("with_plugins")
def test_plugin_loaded():
    assert p.plugin_loaded("search_tweaks")


@pytest.mark.usefixtures("with_plugins")
class TestPlugin:
    def test_deftype(self, search):
        assert search()["defType"] == "edismax"
        assert search(defType="dismax")["defType"] == "dismax"

    @pytest.mark.ckan_config(CONFIG_PREFER_BOOST, "no")
    def test_default_bf(self, search):
        assert search()["bf"] == "0"

    @pytest.mark.ckan_config(CONFIG_PREFER_BOOST, "no")
    def test_modified_bf(self, search):
        result = search(bf="sum(0,1)")
        assert result["bf"] == "sum(0,1)"
        assert "boost" not in result

    @pytest.mark.ckan_config(CONFIG_PREFER_BOOST, "no")
    def test_boost_is_disabled(self, search):
        assert "boost" not in search()

    def test_boost_enabled_by_default_and_empty(self, search):
        result = search()
        assert "bf" not in result
        assert result["boost"] == []

    def test_boost_modified(self, search):
        result = search(boost=["0", "1"])
        assert "bf" not in result
        assert result["boost"] == ["0", "1"]

    def test_default_qf(self, search):
        assert search()["qf"] == query.QUERY_FIELDS

    @pytest.mark.ckan_config(plugin.CONFIG_QF, "title^10 name^0.1")
    def test_modified_qf(self, search):
        assert search()["qf"] == "title^10 name^0.1"


@pytest.mark.usefixtures("with_plugins")
class TestFuzzy:
    def test_fuzzy_disabled(self, search):
        assert search()["q"] == "*:*"
        assert search(q="hello")["q"] == "hello"
        assert search(q="hello world")["q"] == "hello world"
        assert search(q="hello:world")["q"] == "hello:world"
        assert search(q="hello AND world")["q"] == "hello AND world"

    @pytest.mark.ckan_config(plugin.CONFIG_FUZZY, "on")
    @pytest.mark.parametrize("distance", [1, 2])
    def test_fuzzy_enabled(self, search, distance, ckan_config, monkeypatch):
        monkeypatch.setitem(
            ckan_config, plugin.CONFIG_FUZZY_DISTANCE, distance
        )
        assert search()["q"] == "*:*"
        assert search(q="hello")["q"] == f"hello~{distance}"
        assert (
            search(q="hello world")["q"]
            == f"hello~{distance} world~{distance}"
        )
        assert search(q="hello:world")["q"] == f"hello:world"
        assert (
            search(q="hello AND world")["q"]
            == f"hello~{distance} AND world~{distance}"
        )

    @pytest.mark.ckan_config(plugin.CONFIG_FUZZY, "on")
    @pytest.mark.parametrize("distance", [-10, -1, 0])
    def test_fuzzy_enabled_with_too_low_distance(
        self, search, distance, ckan_config, monkeypatch
    ):
        monkeypatch.setitem(
            ckan_config, plugin.CONFIG_FUZZY_DISTANCE, distance
        )
        assert search(q="")["q"] == "*:*"
        assert search(q="hello")["q"] == "hello"
        assert search(q="hello world")["q"] == "hello world"
        assert search(q="hello:world")["q"] == "hello:world"
        assert search(q="hello AND world")["q"] == "hello AND world"

    @pytest.mark.ckan_config(plugin.CONFIG_FUZZY, "on")
    @pytest.mark.parametrize("distance", [3, 20, 111])
    def test_fuzzy_enabled_with_too_high_distance(
        self, search, distance, ckan_config, monkeypatch
    ):
        monkeypatch.setitem(
            ckan_config, plugin.CONFIG_FUZZY_DISTANCE, distance
        )
        assert search()["q"] == "*:*"
        assert search(q="hello")["q"] == "hello~2"
        assert search(q="hello world")["q"] == "hello~2 world~2"
        assert search(q="hello:world")["q"] == "hello:world"
        assert search(q="hello AND world")["q"] == "hello~2 AND world~2"


class TestMoleculeSearch:
    @pytest.mark.parametrize(
        "fq",
        [
            MOLECULE_FQ,
            "dataset_type:molecule",
            'dataset_type:"molecule"',
            ["organization:chemistry", MOLECULE_FQ],
            (MOLECULE_FQ,),
        ],
    )
    def test_detects_supported_molecule_filters(self, fq):
        assert plugin._is_molecule_search({"fq": fq})

    @pytest.mark.parametrize(
        "search_params",
        [
            {},
            {"fq": None},
            {"fq": 1},
            {"fq": [None, 1]},
            {"fq": "dataset_type:dataset"},
            {"fq": "-dataset_type:molecule"},
            {"fq": "notes:dataset_type:molecule"},
            {"fq": "dataset_type:molecules"},
        ],
    )
    def test_rejects_missing_or_unrelated_filters(self, search_params):
        assert not plugin._is_molecule_search(search_params)

    @pytest.mark.ckan_config(
        plugin.CONFIG_MOLECULE_QF, "molecule_names^5 inchi_key^10"
    )
    def test_plain_text_stays_solr_native(self, before_search):
        result = before_search(q="aspirin", fq=MOLECULE_FQ)

        assert result["q"] == "aspirin"
        assert result["qf"].endswith(" molecule_names^5 inchi_key^10")

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    def test_molecule_qf_builds_on_existing_qf(self, before_search):
        result = before_search(
            q="acetylsalicylic acid", fq=MOLECULE_FQ, qf="title^4 notes"
        )

        assert result["qf"] == "title^4 notes molecule_names^5"

    def test_molecule_qf_is_safe_by_default(self, before_search):
        result = before_search(q="aspirin", fq=MOLECULE_FQ)

        assert result["qf"] == query.QUERY_FIELDS

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    @pytest.mark.ckan_config(plugin.CONFIG_FUZZY, "on")
    @pytest.mark.parametrize(
        "query",
        [
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            '"acetylsalicylic acid"',
            "inchi_key:BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "C1=CC=CC=C1",
        ],
    )
    def test_molecule_identifiers_and_syntax_are_not_fuzzified(
        self, before_search, query
    ):
        assert before_search(q=query, fq=MOLECULE_FQ)["q"] == query

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    @pytest.mark.ckan_config(plugin.CONFIG_FUZZY, "on")
    def test_dataset_search_keeps_existing_behavior(self, before_search):
        result = before_search(q="aspirin", fq="dataset_type:dataset")

        assert "molecule_names" not in result["qf"]
        assert result["q"] == "(aspirin~1) OR (aspirin)"

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    def test_empty_molecule_query_has_no_special_processing(
        self, before_search
    ):
        result = before_search(q="", fq=MOLECULE_FQ)

        assert result["q"] == ""
        assert "molecule_names" not in result["qf"]

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    def test_unknown_molecule_word_does_not_raise(self, before_search):
        result = before_search(q="definitelynotamolecule", fq=MOLECULE_FQ)

        assert result["q"] == "definitelynotamolecule"

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    def test_pubchem_unavailability_is_irrelevant(
        self, before_search, monkeypatch
    ):
        from ckanext.search_tweaks.controller import molecule_name_search

        monkeypatch.setattr(
            molecule_name_search,
            "custom_molecule_search",
            lambda *args, **kwargs: pytest.fail("PubChem lookup was called"),
        )

        assert before_search(q="aspirin", fq=MOLECULE_FQ)["q"] == "aspirin"

    @pytest.mark.ckan_config(plugin.CONFIG_MOLECULE_QF, "molecule_names^5")
    def test_boost_and_bf_behavior_remains_intact(
        self, before_search, monkeypatch
    ):
        boosted = before_search(q="aspirin", fq=MOLECULE_FQ)
        assert boosted["boost"] == []
        assert "bf" not in boosted

        monkeypatch.setattr(plugin, "boost_preffered", lambda: False)
        with_bf = before_search(q="aspirin", fq=MOLECULE_FQ)
        assert with_bf["bf"] == "0"
        assert "boost" not in with_bf
