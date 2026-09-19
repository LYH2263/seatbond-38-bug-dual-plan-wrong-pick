import { useEffect, useState } from "react";
import { api } from "../api/client";

type Show = { id: number; film_title: string; hall_name?: string };
type Plan = {
  plan_id: string;
  label: string;
  row: number;
  start_col: number;
  end_col: number;
  score: number;
  distance_to_center: number;
};
type Preview = {
  token: string;
  expires_at: string;
  ttl_seconds: number;
  merged: boolean;
  plans: Plan[];
};
type Hold = {
  id: number;
  order_code: string;
  row: number;
  start_col: number;
  end_col: number;
  party_size: number;
};

export default function HoldPage() {
  const [shows, setShows] = useState<Show[]>([]);
  const [sid, setSid] = useState<number | "">("");
  const [party, setParty] = useState(3);
  const [prefRow, setPrefRow] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [last, setLast] = useState<Hold | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Show[]>("/showtimes").then((s) => {
      setShows(s);
      if (s[0]) setSid(s[0].id);
    });
  }, []);

  async function runPreview() {
    setMsg("");
    setErr("");
    setLast(null);
    setBusy(true);
    try {
      const body: Record<string, unknown> = { showtime_id: sid, party_size: party };
      if (prefRow) body.preferred_row = Number(prefRow);
      const p = await api<Preview>("/holds/preview", { method: "POST", body: JSON.stringify(body) });
      setPreview(p);
    } catch (e) {
      setPreview(null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(planId: string) {
    if (!preview) return;
    setMsg("");
    setErr("");
    setBusy(true);
    try {
      const hold = await api<Hold>("/holds/confirm", {
        method: "POST",
        body: JSON.stringify({ token: preview.token, plan_id: planId }),
      });
      setPreview(null);
      setLast(hold);
      setMsg(`已锁座 ${hold.order_code}：第${hold.row}排 ${hold.start_col}-${hold.end_col}`);
    } catch (e) {
      // 占用已变 / 令牌过期：本次试算作废，必须重新试算
      setPreview(null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!preview) return;
    const token = preview.token;
    setPreview(null);
    setErr("");
    setMsg("已取消试算，未占座");
    try {
      await api("/holds/cancel", { method: "POST", body: JSON.stringify({ token }) });
    } catch {
      /* 令牌已失效也无所谓：取消本就不占座 */
    }
  }

  const [planA, planB] = preview?.plans ?? [];
  const scoreDiff =
    preview && !preview.merged && planA && planB
      ? Math.abs(planA.score - planB.score).toFixed(1)
      : null;
  const nearer =
    preview && !preview.merged && planA && planB
      ? planA.distance_to_center === planB.distance_to_center
        ? null
        : planA.distance_to_center < planB.distance_to_center
          ? planA
          : planB
      : null;

  return (
    <>
      <h2>锁座 · 双方案试算</h2>
      <div className="toolbar">
        <select value={sid} onChange={(e) => setSid(Number(e.target.value))}>
          {shows.map((s) => (
            <option key={s.id} value={s.id}>
              {s.film_title} · {s.hall_name}
            </option>
          ))}
        </select>
        <label>
          人数{" "}
          <input
            type="number"
            min={1}
            max={12}
            value={party}
            onChange={(e) => setParty(Number(e.target.value))}
            style={{ width: 72 }}
          />
        </label>
        <label>
          优先排{" "}
          <input
            value={prefRow}
            onChange={(e) => setPrefRow(e.target.value)}
            placeholder="可选"
            style={{ width: 72 }}
          />
        </label>
        <button onClick={runPreview} disabled={busy || sid === ""}>
          试算双方案
        </button>
        {preview && (
          <button className="btn-ghost" onClick={cancel} disabled={busy}>
            取消
          </button>
        )}
      </div>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="err">{err}</div>}

      {preview && (
        <section className="preview-panel">
          <p className="preview-hint">
            试算未占座。请在 {preview.ttl_seconds} 秒内确认其中一套方案；取消或离开均不占座。
          </p>
          <div className="plan-grid">
            {preview.plans.map((p) => (
              <div
                key={p.plan_id}
                className={`plan-card${nearer && nearer.plan_id === p.plan_id ? " plan-card--best" : ""}`}
              >
                <div className="plan-label">{p.label}</div>
                <div className="plan-coords">
                  R{p.row} · C{p.start_col}-{p.end_col}
                </div>
                <div className="plan-meta">
                  <span>居中得分 {p.score.toFixed(1)}</span>
                  <span>距中线 {p.distance_to_center} 列</span>
                </div>
                <button
                  onClick={() => {
                    const other = preview.plans.find((x) => x.plan_id !== p.plan_id);
                    confirm(other ? other.plan_id : p.plan_id);
                  }}
                  disabled={busy}
                >
                  确认此方案
                </button>
              </div>
            ))}
          </div>
          {preview.merged ? (
            <p className="plan-diff">两套策略试算结果一致，合并为一套方案；确认后只落一条持座。</p>
          ) : (
            scoreDiff && (
              <p className="plan-diff">
                得分差异 {scoreDiff} 分
                {nearer
                  ? ` · 「${nearer.label}」段中点距厅中线更近（${nearer.distance_to_center} 列）`
                  : " · 两方案距中线相同"}
                ；确认后只落所选一条。
              </p>
            )
          )}
        </section>
      )}

      {last && (
        <p className="mono">
          订单 {last.order_code} · {last.party_size} 人 · R{last.row} C{last.start_col}-{last.end_col}
        </p>
      )}
    </>
  );
}
