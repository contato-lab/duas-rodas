#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GA4 -> ga4-data.json (Revista Duas Rodas) — forca da marca (trafego do site).
Autenticacao: OAuth2 (se os secrets GOOGLE_ADS_* existirem) senao ADC/WIF (conta de servico).
Roda via GitHub Actions. Le pela API do GA4 a propriedade GA4_PROPERTY_ID.
"""
import json, os
from datetime import datetime, timezone

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, OrderBy, RunReportRequest,
)

PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "40156199")
OUT_FILE = "ga4-data.json"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def get_client():
    rt = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
    cid = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    cs = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    if rt and cid and cs:
        print("GA4: autenticando via OAuth2 (refresh token)")
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials(token=None, refresh_token=rt,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=cid, client_secret=cs, scopes=SCOPES)
        creds.refresh(Request())
        return BetaAnalyticsDataClient(credentials=creds)
    print("GA4: autenticando via ADC / Workload Identity Federation")
    return BetaAnalyticsDataClient()


def main():
    client = get_client()
    prop = f"properties/{PROPERTY_ID}"

    # serie diaria (90 dias)
    r = client.run_report(RunReportRequest(
        property=prop,
        date_ranges=[DateRange(start_date="90daysAgo", end_date="today")],
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"),
                 Metric(name="newUsers"), Metric(name="screenPageViews")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
        limit=400,
    ))
    daily, ts, tu, tp = [], 0, 0, 0
    for row in r.rows:
        d = row.dimension_values[0].value
        v = [int(m.value) for m in row.metric_values]
        daily.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                      "sessions": v[0], "users": v[1], "new_users": v[2], "pageviews": v[3]})
        ts += v[0]; tu += v[1]; tp += v[3]

    # canais (origem do trafego) - ultimos 28 dias
    canais = []
    try:
        rc = client.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date="28daysAgo", end_date="today")],
            dimensions=[Dimension(name="sessionDefaultChannelGroup")],
            metrics=[Metric(name="sessions")],
            order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
            limit=8,
        ))
        for row in rc.rows:
            canais.append({"canal": row.dimension_values[0].value,
                           "sessions": int(row.metric_values[0].value)})
    except Exception as e:
        print("[ga4-canais]", e)

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "property": PROPERTY_ID,
        "totals": {"sessions": ts, "users": tu, "pageviews": tp},
        "daily": daily,
        "canais": canais,
    }
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_FILE)
    print(f"OK ga4-data.json: {ts} sessoes, {tu} usuarios, {len(daily)} dias, {len(canais)} canais")


if __name__ == "__main__":
    main()
