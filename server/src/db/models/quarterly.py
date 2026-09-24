"""Quarterly metrics (Excel: Quarterly_Metrics)."""
from tortoise import fields
from tortoise.models import Model


class QuarterlyMetrics(Model):
    id = fields.IntField(pk=True)
    scrip_code = fields.CharField(max_length=32, index=True)
    period = fields.CharField(max_length=64, index=True)
    category = fields.CharField(max_length=16, index=True)  # std | con
    metrics_json = fields.TextField(null=True)
    currency = fields.CharField(max_length=16, null=True)
    level_of_rounding = fields.CharField(max_length=64, null=True)

    sales = fields.FloatField(null=True)
    exceptional_items = fields.FloatField(null=True)
    other_income_normal = fields.FloatField(null=True)
    interest = fields.FloatField(null=True)
    depreciation = fields.FloatField(null=True)
    profit_before_tax = fields.FloatField(null=True)
    profit_after_tax = fields.FloatField(null=True)
    tax = fields.FloatField(null=True)
    eps_in_rs = fields.FloatField(null=True)
    net_profit = fields.FloatField(null=True)
    other_income = fields.FloatField(null=True)
    expenses = fields.FloatField(null=True)
    operating_profit = fields.FloatField(null=True)
    ebitda = fields.FloatField(null=True)
    revenue_growth_percent = fields.FloatField(null=True)
    ebitda_margin_percent = fields.FloatField(null=True)
    ebit = fields.FloatField(null=True)
    opm_percent = fields.FloatField(null=True)
    tax_percent = fields.FloatField(null=True)
    net_profit_margin = fields.FloatField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "Quarterly_Metrics"
        unique_together = (("scrip_code", "period", "category"),)
