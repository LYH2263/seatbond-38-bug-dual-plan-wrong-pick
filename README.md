# SeatBond

影院连座锁座：按场次厅图查找连续空座，过道列断开，冲突检测既有持座。

锁座为「试算 → 确认」两段式：试算一次返回两套预览方案（最左连续、居中优选），
附带短时确认令牌；两套坐标相同则合并为一套。确认时必须指明选中的方案并携带令牌，
占用已变或令牌过期会被拒绝并提示重新试算；取消或离开确认页不占座，一次确认只落一条持座。

居中得分规则：段中点距厅中线越近分越高（0-100），同分依次比排号、起始列（小者优先）。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4100 |
| API | http://localhost:9100 |
| API 文档 | http://localhost:9100/docs |
| Postgres | localhost:5442 |

健康检查：`GET http://localhost:9100/api/health`

## 页面

- `/halls` — 影厅
- `/showtimes` — 场次
- `/seatmap` — 座位图（大网格热力）
- `/hold` — 锁座
- `/orders` — 订单
- `/conflicts` — 冲突

## 使用说明

1. 在影厅与场次页确认厅图与排期。
2. 打开座位图查看占用热力，在锁座页输入连座人数并「试算双方案」。
3. 并排比较两套方案（坐标、居中得分、距中线列数），点选其中一套「确认此方案」落座；取消或离开不占座。
4. 订单页查看持座结果；冲突页查看重叠请求。

## 接口

- `POST /api/holds/preview` — 试算：返回两套方案与短时确认令牌（默认 120 秒，`PREVIEW_TTL_SECONDS` 可调），不占座。
- `POST /api/holds/confirm` — 确认：携带 `token` 与 `plan_id`，仅落所选一条；占用变化或令牌过期返回 409 并提示重新试算。
- `POST /api/holds/cancel` — 取消试算：令牌作废，不落座（幂等）。
- `POST /api/holds` — 旧版直接锁座（保留兼容）。

## 开发与测试

```bash
docker compose exec api pytest -q
```
