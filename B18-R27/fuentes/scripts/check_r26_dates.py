"""Read a finished R25 local validation, verify the operator's board and print aggregates only."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from app.practice_board import practice_search
from app.security import issue_session, token_digest


def check(run):
    root = run / "datos"
    db = root / "app.sqlite3"
    wal = Path(str(db) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Se necesita una validación terminada sin cambios pendientes en WAL.")
    previous = set(map(int,json.loads((run/"estados-por-fila.json").read_text(encoding="utf-8"))))
    with closing(sqlite3.connect(db.as_uri()+"?mode=ro&immutable=1",uri=True)) as source, \
            closing(sqlite3.connect(":memory:",isolation_level=None)) as conn:
        source.execute("PRAGMA query_only=ON")
        source.backup(conn)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store=MEMORY")
        batches = conn.execute("SELECT b.id,b.dataset_id,i.period FROM batches b JOIN current_invoice_imports i ON i.batch_id=b.id").fetchall()
        if len(batches)!=1 or batches[0]["period"]!="2026-08" or len(previous)!=357:
            raise ValueError("La validación no contiene el lote de agosto y la cohorte R25 previstos.")
        actor = conn.execute("SELECT id FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()[0]
        token = token_digest(issue_session(conn,actor)[0])
        conn.execute("PRAGMA query_only=ON")
        def page(view,offset=0,**extra):
            batch = batches[0]
            return practice_search(conn,token,batch["dataset_id"],batch["id"],
                                   dict(family="images",scope="included",view=view,limit=100,offset=offset,**extra),root=root)
        def all_rows(view,**extra):
            first = page(view,**extra)
            items = first["items"][:]
            for offset in range(100,first["filtered_total"],100):
                items.extend(page(view,offset,**extra)["items"])
            assert len(items)==len({r["source_row"] for r in items})==first["filtered_total"]
            return items
        images = all_rows("all")
        counts = Counter()
        dates = []
        late = set()
        amounts = Decimal(0)
        end = date(2026,8,31)
        cutoff = end - timedelta(days=45)
        for row in images:
            number = row["source_row"]
            day = date.fromisoformat(row["practice_date"])
            days = (end-day).days
            expected = "late" if day < cutoff else "in_term"
            assert days>=0 and row["billing_window"]==dict(status=expected,days=days,close=end.isoformat())
            group = "357_originales" if number in previous else "incorporadas"
            counts[group,expected] += 1
            if number in previous:
                dates.append(day)
            if expected=="late":
                late.add(number)
                decision = row["administrative_decision"]
                assert decision and decision["proposal"]["amount_ars"]==row["total_ars"]
                amounts += Decimal(row["total_ars"])
            else:
                assert not row.get("late_billing_reason")
        assert len(dates)==len(previous)
        filtered = all_rows("exceptions",exception_reason="Facturación fuera de término")
        assert late=={r["source_row"] for r in filtered}
        assert conn.execute("SELECT count(*) FROM invoice_row_decisions").fetchone()[0]==0
        return dict(periodo="2026-08",desde=cutoff.isoformat(),cierre=end.isoformat(),
                    fechas_cohorte_R25=[min(dates).isoformat(),max(dates).isoformat()],
                    imagenes_revisables=len(images),por_grupo={g:{s:counts[g,s] for s in ("in_term","late")}
                        for g in ("357_originales","incorporadas")},total_fuera_de_termino=len(late),
                    total_propuesto_por_plazo_ARS=format(amounts,".2f"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--validacion-r25",required=True,type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.validacion_r25.resolve()),ensure_ascii=True))
