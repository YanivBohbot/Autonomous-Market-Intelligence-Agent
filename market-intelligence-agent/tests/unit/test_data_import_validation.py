from app.data_import.validation import (
    detect_import_type,
    validate_clients_rows,
    validate_holdings_rows,
)


def test_detects_clients_file_by_its_columns():
    rows = [{"name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
              "risk_profile": "balanced", "advisor": "Sam", "city": "Paris"}]
    assert detect_import_type(rows) == "clients"


def test_detects_holdings_file_by_its_columns():
    rows = [{"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}]
    assert detect_import_type(rows) == "holdings"


def test_detects_neither_for_an_unrelated_file():
    rows = [{"foo": "bar"}]
    assert detect_import_type(rows) is None


def test_detects_nothing_for_an_empty_file():
    assert detect_import_type([]) is None


def _valid_client_row(**overrides):
    row = {"name": "Jane Doe", "email": "jane@x.com", "segment": "VIP",
           "risk_profile": "balanced", "advisor": "Sam", "city": "Paris"}
    row.update(overrides)
    return row


def test_valid_clients_rows_pass():
    result = validate_clients_rows([_valid_client_row()], existing_emails=set())
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["rows"][0]["email"] == "jane@x.com"


def test_clients_rows_default_joined_on_to_today():
    import datetime
    result = validate_clients_rows([_valid_client_row()], existing_emails=set())
    assert result["rows"][0]["joined_on"] == datetime.date.today().isoformat()


def test_clients_row_missing_a_required_field_is_rejected():
    row = _valid_client_row()
    del row["advisor"]
    result = validate_clients_rows([row], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "advisor"


def test_clients_row_with_a_bad_segment_is_rejected():
    result = validate_clients_rows([_valid_client_row(segment="Gold")], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "segment"


def test_clients_row_with_a_bad_risk_profile_is_rejected():
    result = validate_clients_rows([_valid_client_row(risk_profile="risky")], existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "risk_profile"


def test_clients_row_whose_email_already_exists_is_rejected():
    result = validate_clients_rows([_valid_client_row()], existing_emails={"jane@x.com"})
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "email"


def test_clients_file_with_a_duplicate_email_in_itself_is_rejected():
    rows = [_valid_client_row(), _valid_client_row(name="Jane Two")]
    result = validate_clients_rows(rows, existing_emails=set())
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "email"


def test_one_bad_clients_row_blocks_the_whole_file():
    rows = [_valid_client_row(), _valid_client_row(email="other@x.com", segment="Gold")]
    result = validate_clients_rows(rows, existing_emails=set())
    assert result["valid"] is False
    # the good row is not silently imported
    assert len(result["errors"]) == 1


def _valid_holding_row(**overrides):
    row = {"client_email": "jane@x.com", "ticker": "AAPL", "shares": 10, "avg_cost": 150.0}
    row.update(overrides)
    return row


def test_valid_holdings_row_resolves_to_a_client_id():
    result = validate_holdings_rows(
        [_valid_holding_row()],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is True
    assert result["rows"][0]["client_id"] == 7
    assert result["rows"][0]["ticker"] == "AAPL"


def test_holdings_row_with_unknown_client_email_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(client_email="ghost@x.com")],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "client_email"


def test_holdings_row_with_unknown_ticker_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(ticker="ZZZZ")],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "ticker"


def test_holdings_row_with_non_positive_shares_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(shares=0)],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "shares"


def test_holdings_row_with_non_positive_avg_cost_is_rejected():
    result = validate_holdings_rows(
        [_valid_holding_row(avg_cost=-1)],
        client_id_by_email={"jane@x.com": 7},
        known_tickers={"AAPL"},
    )
    assert result["valid"] is False
    assert result["errors"][0]["field"] == "avg_cost"


def test_holdings_file_with_a_duplicate_client_ticker_pair_is_rejected():
    rows = [_valid_holding_row(), _valid_holding_row(shares=20)]
    result = validate_holdings_rows(
        rows, client_id_by_email={"jane@x.com": 7}, known_tickers={"AAPL"}
    )
    assert result["valid"] is False
