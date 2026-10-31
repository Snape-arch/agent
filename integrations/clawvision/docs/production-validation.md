# 生产适配器与 AI 联调

## 自动化入口

```bash
python scripts/stress_adapters.py
python scripts/stress_adapters.py --objects 1000 --rows 100000 --db-operations 5000 --strict
```

默认模式会验证本地对象存储，并把未配置的外部适配器标记为 `skipped`。CI 或上线验收使用 `--strict`，任何未配置、失败或故障注入未被拒绝都会返回非零退出码。

覆盖内容：

- 本地对象存储：8 线程并发读写、吞吐量、临时文件故障与原子替换。
- Parquet：Zstandard 写入、Base64 传输、读取吞吐和截断文件拒绝。
- PostgreSQL：临时表批量读写、吞吐和重复主键回滚。
- S3 / MinIO：对象写入、读取、缺失对象故障及测试对象清理。客户端启用自适应重试、5 秒连接超时和 15 秒读取超时。

外部模式需要安装 `requirements-optional.txt` 并配置：

```text
DATABASE_URL=postgresql://...
ARTIFACT_STORE=s3
S3_BUCKET=...
S3_ENDPOINT_URL=...       # AWS S3 可省略
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

凭据永远不要提交到仓库。当前机器没有 PostgreSQL、Docker、MinIO 或 S3 凭据，因此外部服务测试必须在具备这些资源的部署环境运行；工具会明确报告 `skipped`，不会伪造“通过”。

## DeepSeek 联调结论

2026-07-15 使用临时请求凭据完成两条真实 HTTPS 联调：

- 3D Prompt 返回 14 部件 `model3d` 计划并通过 Schema 和几何校验。
- 实验 Prompt 正确产生 `learningRate=0.0003` patch、Embedding Evolution 视图和对应 Run config。

默认模型已更新为 `deepseek-v4-flash`，请求启用 JSON Output 与非思考模式。API Key 只存在于浏览器组件状态和单次请求内，不保存到数据库、对象存储、日志或文档。

## Asset release and recovery acceptance (2026-10-03)

The production browser suite now covers asset approval and standalone Worker
checkpoint recovery. PostgreSQL/MinIO/Nginx acceptance is wired into the isolated
Compose CI gate; container execution remains pending. See
[Asset release and recovery acceptance](asset-release-recovery.md) for changes,
commands, test scope and local results.
