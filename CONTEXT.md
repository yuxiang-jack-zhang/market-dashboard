# Market Dashboard

A personal dashboard for catching up on the market once a day: how the whole market is doing, the names Jack follows, and the market news. It is not for intraday trading.

## Language

**Market** (the Group):
The Group of tickers and rates that describe the whole market rather than one company, such as indices, VIX, Treasury yields, currencies, commodities and BTC. When "the market" is used loosely, it means the market in general, not this Group.
_Avoid_: Gauges, macro tickers, benchmarks

**Watchlist**:
The standing set of individual companies Jack always follows.
_Avoid_: Favorites, tickers I care about

**Theme**:
A named basket of tickers that Jack picks by hand because it matters right now (e.g. "Memory"). Jack creates, renames and deletes Themes by hand; deleting a Theme retires it. A Theme may carry a short note on why it matters.
_Avoid_: Sector, trend, hot list

**Headlines**:
General market news that isn't tied to any particular ticker on the dashboard.
_Avoid_: Ticker news, feed

**Symbol**:
One item in a Group: either a Yahoo symbol (e.g. `MU`, `000660.KS`, `^VIX`) or a FRED series ID (e.g. `DGS2`). Each Symbol remembers which source it came from.
_Avoid_: Ticker (when the item may be a rate series), instrument

**Group**:
One of Market, Watchlist or a Theme. A Group is an ordered list of Symbols, and the same Symbol may appear in more than one Group.

## Relationships

- The dashboard shows **Market**, **Headlines**, the **Watchlist**, then zero or more **Themes**, in that order
- A ticker can belong to several **Groups** at once (e.g. MU in both the **Watchlist** and the "Memory" **Theme**)

## Flagged ambiguities

- "Tickers relevant recently" was resolved as **Theme**: a list Jack curates by hand, not one detected automatically.
