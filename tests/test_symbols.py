from app import symbols


def test_kinds():
    assert symbols.yahoo_kind("^TNX", "CBOE Interest Rate 10 Year T Note") == "rate"
    assert symbols.yahoo_kind("^VIX", "CBOE Volatility Index") == "vol"
    assert symbols.yahoo_kind("^VXSOMETHING", "Some Volatility Index") == "vol"
    assert symbols.yahoo_kind("HKD=X", "USD/HKD") == "peg"
    assert symbols.yahoo_kind("MU", "Micron Technology, Inc.") == "price"
    assert symbols.fred_kind("Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity", "Percent") == "rate"
    assert symbols.fred_kind("ICE BofA US High Yield Index Option-Adjusted Spread", "Percent") == "spread"
    assert symbols.fred_kind("10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity", "Percent") == "spread"
    assert symbols.fred_kind("CBOE Volatility Index: VIX", "Index") == "price"


def test_symbol_format():
    for ok in ["MU", "^GSPC", "000660.KS", "GBPUSD=X", "BTC-USD", "CL=F", "DX-Y.NYB", "BAMLH0A0HYM2"]:
        assert symbols.is_valid_format(ok), ok
    for bad in ["", "SK HYNIX", "MU;DROP", "A" * 30, "-MU", "mu"]:
        assert not symbols.is_valid_format(bad), bad
    assert symbols.normalize("  mu ") == "MU"


def test_default_subsection():
    assert symbols.default_subsection("fred", "rate", None, "Mortgage") == "rates"
    assert symbols.default_subsection("yahoo", "price", "CURRENCY", "EUR/USD") == "fx"
    assert symbols.default_subsection("yahoo", "price", "INDEX", "US Dollar Index") == "fx"
    assert symbols.default_subsection("yahoo", "price", "CRYPTOCURRENCY", "Ethereum USD") == "crypto"
    assert symbols.default_subsection("yahoo", "price", "FUTURE", "Silver Dec 26") == "commodities"
    assert symbols.default_subsection("yahoo", "price", "FUTURE", "E-Mini S&P 500 Dec 26") == "indices"
    assert symbols.default_subsection("yahoo", "price", "FUTURE", "10-Year T-Note Futures") == "rates"
    assert symbols.default_subsection("yahoo", "vol", "INDEX", "CBOE Volatility Index") == "indices"
    assert symbols.default_subsection("yahoo", "price", "EQUITY", "Apple") == "indices"


def test_decimals():
    assert symbols.decimals("price", "EQUITY", "USD", 2, 1074.89) == 2
    assert symbols.decimals("price", "EQUITY", "KRW", 2, 1841000) == 0
    assert symbols.decimals("price", "CURRENCY", "USD", 4, 1.32) == 4
    assert symbols.decimals("price", "CURRENCY", "JPY", 4, 158.1) == 2
    assert symbols.decimals("peg", "CURRENCY", "HKD", 4, 7.8465) == 4
    assert symbols.decimals("price", "CRYPTOCURRENCY", "USD", 2, 85520.14) == 0
    assert symbols.decimals("rate", "INDEX", "USD", 4, 5.277) == 2


def test_labels():
    assert symbols.default_label("yahoo", "MU", "Micron Technology, Inc.") == "Micron Technology"
    assert symbols.default_label("yahoo", "CL=F", "Crude Oil Nov 26") == "Crude Oil"
    assert symbols.default_label("yahoo", "XYZ", None) == "XYZ"
    assert symbols.default_label("fred", "MORTGAGE30US", "30-Year Fixed Rate Mortgage Average") == "MORTGAGE30US"
