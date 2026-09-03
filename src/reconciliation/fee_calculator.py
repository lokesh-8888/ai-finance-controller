"""Mathematical gateway fee calculation and merchant bracket boundary validation."""

from typing import Tuple
from src.ingestion.normalizer import cents_to_display


class GatewayFeeCalculator:
    """Validates mathematical consistency of payment processing fees.

    Supports standard credit card processor schedules (Stripe 2.9% + $0.30)
    and configurable merchant interchange brackets (2.0% - 3.5% + $0.30)
    to prevent false-positive matching of arbitrary financial discrepancies.
    """

    DEFAULT_MIN_RATE = 0.020  # 2.0% lower bound
    DEFAULT_MAX_RATE = 0.035  # 3.5% upper bound
    DEFAULT_FIXED_FEE_CENTS = 30  # $0.30 fixed fee per transaction

    @staticmethod
    def calculate_stripe_fee(gross_cents: int) -> int:
        """Calculate standard Stripe credit card fee: 2.9% + $0.30."""
        if gross_cents <= 0:
            return 0
        return int(round(gross_cents * 0.029)) + 30

    @classmethod
    def is_within_merchant_brackets(
        cls,
        gross_cents: int,
        fee_cents: int,
        min_rate: float = DEFAULT_MIN_RATE,
        max_rate: float = DEFAULT_MAX_RATE,
        fixed_cents: int = DEFAULT_FIXED_FEE_CENTS,
    ) -> bool:
        """Verify whether fee_cents falls strictly within acceptable merchant fee brackets.

        Min fee: gross * 2.0%
        Max fee: (gross * 3.5%) + $0.30 + $0.20 rounding slack
        """
        if gross_cents <= 0 or fee_cents <= 0:
            return False

        min_fee = int(gross_cents * min_rate)
        max_fee = int(round(gross_cents * max_rate)) + fixed_cents + 20

        return min_fee <= fee_cents <= max_fee

    @classmethod
    def validate_net_settlement(
        cls,
        gross_cents: int,
        net_cents: int,
        tax_cents: int = 0,
        tolerance_cents: int = 2,
    ) -> Tuple[bool, int, str]:
        """Validate whether Bank Deposit == Gross - Fee - Tax.

        Returns:
            (is_valid, calculated_fee_cents, audit_explanation)
        """
        actual_variance = gross_cents - net_cents - tax_cents
        if actual_variance <= 0:
            return False, 0, "Variance is non-positive; not a fee deduction"

        # Check exact Stripe formula first (2.9% + $0.30)
        expected_stripe_fee = cls.calculate_stripe_fee(gross_cents)
        if abs(actual_variance - expected_stripe_fee) <= tolerance_cents:
            explanation = (
                f"Variance of {cents_to_display(actual_variance)} precisely matches "
                f"standard Stripe fee ({cents_to_display(expected_stripe_fee)}) "
                f"on gross {cents_to_display(gross_cents)} (2.9% + $0.30)."
            )
            return True, actual_variance, explanation

        # Fallback: check within valid merchant fee bracket (2.0% - 3.5% + $0.30)
        if cls.is_within_merchant_brackets(gross_cents, actual_variance):
            explanation = (
                f"Variance of {cents_to_display(actual_variance)} falls within "
                f"acceptable merchant fee bracket [2.0%, 3.5% + $0.30] "
                f"for gross {cents_to_display(gross_cents)}."
            )
            return True, actual_variance, explanation

        return False, actual_variance, (
            f"Variance of {cents_to_display(actual_variance)} does NOT conform "
            f"to any recognized gateway fee schedule."
        )
