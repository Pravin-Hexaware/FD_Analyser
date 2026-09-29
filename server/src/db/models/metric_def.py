"""Metric catalog (Excel: Metrics) — particulars + IND-AS XBRL tags / formulas."""
from tortoise import fields
from tortoise.models import Model


class MetricDefinition(Model):
    id = fields.IntField(pk=True)
    metric_category = fields.CharField(max_length=64)  # quarterly | Annual
    sub_category = fields.CharField(max_length=64)  # quarterly | P&L | Balancesheet | Cashflow | Ratios
    particulars = fields.CharField(max_length=255)
    # XBRL localname (e.g. RevenueFromOperations) OR formula (e.g. Sales-Expenses, (EBITDA/Sales)*100)
    ind_as = fields.CharField(max_length=512, null=True)

    class Meta:
        table = "Metrics"

    def __str__(self) -> str:
        return f"{self.metric_category}/{self.sub_category}: {self.particulars}"
