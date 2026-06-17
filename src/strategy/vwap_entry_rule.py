def get_vwap_entry_threshold(vwap: float, price_ratio: float) -> float:
    """Create the VWAP entry threshold price.

    @param vwap: Current VWAP.
    @param price_ratio: Ratio applied to VWAP. 1.0 keeps the default rule, below 1.0 relaxes it, above 1.0 strengthens it.
    @returns: Entry threshold price.
    """
    return vwap * price_ratio


def is_price_above_vwap_entry_threshold(current_price: int | float, vwap: float, price_ratio: float) -> bool:
    """Check whether current price passes the VWAP entry threshold.

    @param current_price: Current traded price.
    @param vwap: Current VWAP.
    @param price_ratio: Ratio applied to VWAP. 1.0 keeps the default rule, below 1.0 relaxes it, above 1.0 strengthens it.
    @returns: True when current price is above the configured VWAP threshold.
    """
    return current_price > get_vwap_entry_threshold(vwap, price_ratio)
