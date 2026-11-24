import datetime
from unittest.mock import AsyncMock, Mock

import polars as pl
import pytest

from ziplime.assets.entities.exchange_asset import ExchangeAsset
from ziplime.errors import LiquidityExceeded
from ziplime.exchanges.exchange import Exchange
from ziplime.finance.domain.order import Order
from ziplime.finance.domain.order_status import OrderStatus
from ziplime.finance.execution import LimitOrder, MarketOrder
from ziplime.finance.slippage.volume_share_slippage import VolumeShareSlippage


@pytest.fixture
def dt():
    return datetime.datetime(2026, 9, 25, 14, tzinfo=datetime.timezone.utc)


@pytest.fixture
def asset():
    return Mock(spec=ExchangeAsset, symbol="TEST")


@pytest.fixture
def exchange():
    exchange = Mock(spec=Exchange)
    exchange.name = "TEST"
    exchange.get_spot_value = AsyncMock(
        return_value=pl.DataFrame({"open": [90.0], "close": [100.0], "volume": [1000.0]}),
    )
    return exchange


@pytest.fixture
def order(dt, asset):
    return Order(
        id="order", dt=dt, asset=asset, amount=100, filled=0, commission=0.0,
        execution_style=MarketOrder(), status=OrderStatus.OPEN,
        exchange_name="TEST", trading_account_id="account",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("price", [None, 90.0, 0.0])
async def test_process_order_uses_exchange_data_and_optional_execution_price(exchange, dt, order, direction, price):
    order.amount *= direction
    order.direction = float(direction)
    model = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)

    execution_price, amount = await model.process_order(exchange, dt, order, price=price)

    base_price = 100.0 if price is None else price
    assert execution_price == pytest.approx(base_price * (1 + direction * 0.1 * 0.025 ** 2))
    assert amount == 25 * direction
    exchange.get_spot_value.assert_awaited_once_with(
        assets=frozenset({order.asset}), fields=frozenset({"volume", "close"}), dt=dt,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_price", [None, float("nan")])
async def test_process_order_returns_no_fill_for_missing_close(exchange, dt, order, missing_price):
    exchange.get_spot_value.return_value = pl.DataFrame({"close": [missing_price], "volume": [1000.0]})

    assert await VolumeShareSlippage().process_order(exchange, dt, order) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("volume", [0.0, 20.0])
async def test_process_order_raises_when_volume_cannot_fill_a_share(exchange, dt, order, volume):
    exchange.get_spot_value.return_value = pl.DataFrame({"close": [100.0], "volume": [volume]})

    with pytest.raises(LiquidityExceeded):
        await VolumeShareSlippage().process_order(exchange, dt, order)


@pytest.mark.asyncio
async def test_process_order_respects_limit_after_price_impact(exchange, dt, order):
    order.limit = LimitOrder(100.0).get_limit_price(is_buy=True)

    assert await VolumeShareSlippage().process_order(exchange, dt, order) == (None, None)


@pytest.mark.asyncio
async def test_simulate_uses_selected_price_and_cumulative_bar_volume(exchange, dt, asset, order):
    order.amount = 10
    second_order = Order(
        id="second", dt=dt, asset=asset, amount=100, filled=0, commission=0.0,
        execution_style=MarketOrder(), status=OrderStatus.OPEN,
        exchange_name="TEST", trading_account_id="account",
    )
    model = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)

    fills = [
        (filled_order, transaction)
        async for filled_order, transaction in model.simulate(
            exchange, frozenset({asset}), [order, second_order], dt,
            same_bar_execution=True, price_used_in_order_execution="open",
        )
    ]

    assert [filled_order for filled_order, _ in fills] == [order, second_order]
    assert [transaction.amount for _, transaction in fills] == [10, 15]
    assert [transaction.price for _, transaction in fills] == pytest.approx([
        90.0 * (1 + 0.1 * 0.01 ** 2),
        90.0 * (1 + 0.1 * 0.025 ** 2),
    ])
    assert model.volume_for_bar == 25


@pytest.mark.asyncio
async def test_simulate_preserves_fractional_fill(exchange, dt, asset, order):
    from ziplime.finance.slippage.no_slippage import NoSlippage

    order.amount = 0.75
    model = NoSlippage()
    fills = [
        transaction.amount
        async for _, transaction in model.simulate(
            exchange, frozenset({asset}), [order], dt,
            same_bar_execution=True, price_used_in_order_execution="open",
        )
    ]
    assert fills == [0.75]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_name, expected", [
    ("NoSlippage", 0.75), ("FixedSlippage", 0),
    ("FixedBasisPointsSlippage", 0), ("VolumeShareSlippage", 0), ("unmapped", 0),
])
async def test_simulation_order_quantity_is_model_scoped(dt, asset, model_name, expected):
    from ziplime.exchanges.simulation_exchange import SimulationExchange
    from ziplime.finance.slippage.fixed_basis_points_slippage import FixedBasisPointsSlippage
    from ziplime.finance.slippage.fixed_slippage import FixedSlippage
    from ziplime.finance.slippage.no_slippage import NoSlippage
    from ziplime.trading.trading_algorithm import TradingAlgorithm

    classes = (NoSlippage, FixedSlippage, FixedBasisPointsSlippage, VolumeShareSlippage)
    exchange = Mock(spec=SimulationExchange, name="simulated")
    exchange.name = "TEST"
    exchange.account_id = "account"
    if model_name == "unmapped":
        exchange.get_slippage_model.side_effect = lambda asset: SimulationExchange._model_for(
            {}, asset, "slippage"
        )
    else:
        exchange.get_slippage_model.return_value = next(c for c in classes if c.__name__ == model_name)()
    exchange.submit_order = AsyncMock(side_effect=lambda *, order: order)
    asset.asset = object()
    asset.mic = "TEST"
    algorithm = Mock()
    algorithm.simulation_dt = dt
    algorithm.new_orders = {}
    algorithm._in_before_trading_start = False
    algorithm.exchange_repository.get_default_exchange = AsyncMock(return_value=exchange)
    algorithm.validate_order_params = AsyncMock()

    await TradingAlgorithm.order(algorithm, asset, 0.75, style=MarketOrder())

    assert exchange.submit_order.await_args.kwargs["order"].amount == expected


@pytest.mark.asyncio
async def test_fixed_basis_points_keeps_integer_transaction(exchange, dt, asset, order):
    from ziplime.finance.slippage.fixed_basis_points_slippage import FixedBasisPointsSlippage

    order.amount = 1.75
    fills = [
        transaction.amount
        async for _, transaction in FixedBasisPointsSlippage().simulate(
            exchange, frozenset({asset}), [order], dt,
            same_bar_execution=True, price_used_in_order_execution="open",
        )
    ]
    assert fills == [1]
