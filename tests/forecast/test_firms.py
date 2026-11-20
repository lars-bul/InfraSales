from infrasales.forecast.firms import firm_key


def test_one_firm_however_its_notices_write_its_name() -> None:
    assert firm_key("Müller Rohrleitungsbau GmbH & Co. KG") == firm_key(
        "MÜLLER Rohrleitungsbau GmbH u. Co KG"
    )
    assert firm_key("Max Bögl Stiftung & Co.KG") == "max bögl stiftung"
    assert firm_key("Strauß Tiefbau AG") == "strauss tiefbau"
