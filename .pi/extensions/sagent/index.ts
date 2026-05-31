import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const execFileAsync = promisify(execFile);

async function runPython(cwd: string, script: string, args: string[] = []) {
	const scriptPath = path.join(cwd, "scripts", script);
	const { stdout, stderr } = await execFileAsync(
		"python",
		[scriptPath, ...args],
		{
			cwd,
			encoding: "utf8",
			windowsHide: true,
		},
	);

	return {
		stdout: stdout.trim(),
		stderr: stderr.trim(),
	};
}

async function runPythonSafe(cwd: string, script: string, args: string[] = []) {
	try {
		return { ok: true, ...(await runPython(cwd, script, args)) };
	} catch (error) {
		return {
			ok: false,
			stdout: JSON.stringify(
				{
					ok: false,
					error: error instanceof Error ? error.message : String(error),
				},
				null,
				2,
			),
			stderr: "",
		};
	}
}

function parseJson(text: string) {
	try {
		return JSON.parse(text);
	} catch {
		return { raw: text };
	}
}

function buildScanNotification(scanStdout: string) {
	const data = parseJson(scanStdout) as {
		trade_date?: string;
		mode?: string;
		judgement_model?: string;
		candidates?: Array<{
			symbol?: string;
			name?: string;
			sector?: string;
			reason?: string;
			risk?: string;
		}>;
		warning?: string;
	};

	const lines = [
		`交易日：${data.trade_date ?? "未知"}`,
		`模式：${data.mode ?? "未知"}`,
		`判断模型：${data.judgement_model ?? "GLM5.1"}`,
		`候选数量：${data.candidates?.length ?? 0}`,
	];

	if (data.warning) lines.push(`提示：${data.warning}`);

	for (const candidate of data.candidates ?? []) {
		lines.push(
			"",
			`- ${candidate.symbol ?? "未知代码"} ${candidate.name ?? ""}`.trim(),
			`  板块：${candidate.sector ?? "未知"}`,
			`  理由：${candidate.reason ?? "未提供"}`,
			`  风险：${candidate.risk ?? "未提供"}`,
		);
	}

	return lines.join("\n");
}

export default function sagentExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		ctx.ui.setStatus("sagent", "sagent 已加载");
	});

	pi.registerTool({
		name: "market_scan",
		label: "Market Scan",
		description: "执行 sagent A 股市场扫描。骨架阶段返回 mock 候选股。",
		promptSnippet: "执行 A 股主线交易市场扫描，默认使用 GLM5.1 判断规则。",
		promptGuidelines: [
			"使用 market_scan 时，必须说明当前骨架阶段尚未接入真实 AKShare 数据。",
			"使用 market_scan 的输出时，必须提醒用户不构成投资建议。",
		],
		parameters: Type.Object({
			mock: Type.Optional(
				Type.Boolean({ description: "是否强制使用 mock 数据" }),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args =
				params.mock === false
					? ["--fixture", "fixtures/market/sample_market.json"]
					: ["--mock"];
			const result = await runPython(ctx.cwd, "market_scan.py", args);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	pi.registerTool({
		name: "check_portfolio",
		label: "Check Portfolio",
		description: "读取或初始化 sagent 本地 portfolio.json 持仓状态。",
		promptSnippet: "检查本地 portfolio.json 持仓状态。",
		parameters: Type.Object({
			init: Type.Optional(
				Type.Boolean({
					description: "如果文件不存在，是否初始化 portfolio.json",
				}),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const command = params.init ? "init" : "check";
			const result = await runPython(ctx.cwd, "portfolio.py", [command]);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	pi.registerTool({
		name: "send_feishu_notification",
		label: "Send Feishu Notification",
		description:
			"发送 sagent 飞书机器人通知。未配置 SAGENT_FEISHU_WEBHOOK 时安全跳过。",
		promptSnippet: "把 sagent 扫描或持仓监控结果推送到飞书。",
		promptGuidelines: [
			"使用 send_feishu_notification 时，必须提醒用户该通知仅作研究和辅助分析，不构成投资建议。",
			"send_feishu_notification 不会展示或回传飞书 webhook 密钥。",
		],
		parameters: Type.Object({
			title: Type.Optional(Type.String({ description: "通知标题" })),
			text: Type.String({ description: "通知正文" }),
			dryRun: Type.Optional(
				Type.Boolean({ description: "只构造消息，不实际发送" }),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args = [
				"--title",
				params.title ?? "sagent 通知",
				"--text",
				params.text,
			];
			if (params.dryRun) args.push("--dry-run");
			const result = await runPython(ctx.cwd, "notify_feishu.py", args);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	pi.registerTool({
		name: "analyze_stock",
		label: "Analyze Stock",
		description: "生成单只股票的 K 线自然语言描述。骨架阶段返回 mock 描述。",
		promptSnippet: "把个股 K 线转成自然语言描述，供 GLM5.1 判断形态。",
		parameters: Type.Object({
			symbol: Type.String({ description: "股票代码，例如 000001" }),
			mock: Type.Optional(
				Type.Boolean({ description: "是否强制使用 mock 数据" }),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args = ["--symbol", params.symbol];
			if (params.mock !== false) args.push("--mock");
			const result = await runPython(ctx.cwd, "analyze_stock.py", args);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	pi.registerCommand("scan", {
		description: "执行一次 sagent 每日收盘后扫描",
		handler: async (_args, ctx) => {
			try {
				const result = await runPython(ctx.cwd, "market_scan.py", [
					"--fixture",
					"fixtures/market/sample_market.json",
				]);
				const notification = buildScanNotification(result.stdout);
				const feishuResult = await runPythonSafe(ctx.cwd, "notify_feishu.py", [
					"--title",
					"sagent 扫描结果",
					"--text",
					notification,
				]);
				ctx.ui.notify("sagent /scan 已完成", "info");
				pi.sendMessage(
					{
						customType: "sagent-scan-result",
						content: `# sagent 扫描结果\n\n\`\`\`json\n${result.stdout}\n\`\`\`\n\n## 飞书推送\n\n\`\`\`json\n${feishuResult.stdout}\n\`\`\`\n\n仅作研究和辅助分析，不构成投资建议。`,
						display: true,
						details: {
							stderr: [result.stderr, feishuResult.stderr]
								.filter(Boolean)
								.join("\n"),
							data: parseJson(result.stdout),
							feishu: parseJson(feishuResult.stdout),
						},
					},
					{ triggerTurn: false, deliverAs: "nextTurn" },
				);
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`sagent /scan 失败：${message}`, "error");
			}
		},
	});
}
