from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("senmi", "0013_alter_historicalpackage_price_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE senmi_pricingconfig
                DROP COLUMN IF EXISTS max_demand_multiplier;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]