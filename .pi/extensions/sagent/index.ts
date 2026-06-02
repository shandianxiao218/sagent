import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import fs from "node:fs";

const execFileAsync = promisify(execFile);

// Windows 上 Anaconda python 优先于系统 python（有 mootdx 等依赖）
function getPythonCommand(): string {
	if (process.platform !== "win32") return "python3";
	const candidates = [
		"D:\\ProgramData\\anaconda3\\python.exe",
		"C:\\ProgramData\\anaconda3\\python.exe",
		"C:\\Users\\Administrator\\anaconda3\\python.exe",
	];
	for (const p of candidates) {
		if (fs.existsSync(p)) return p;
	}
	return "python";
}
const PYTHON = getPythonCommand();

async function runPython(cwd: string, script: string, args: string[] = []) {
	const scriptPath = path.join(cwd, "scripts", script);
	const { stdout, stderr } = await execFileAsync(
		PYTHON,
		[scriptPath, ...args],
		{
			cwd,
			encoding: "utf8",
			windowsHide: true,
		},
	);
	return { stdout: stdout.trim(), stderr: stderr.trim() };
}

async function runPythonSafe(cwd: string, script: string, args: string[] = []) {
	try {
		return { ok: true as const, ...(await runPython(cwd, script, args)) };
	} catch (error) {
		return {
			ok: false as const,
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

export default function sagentExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		ctx.ui.setStatus("sagent", "sagent 已加载");
	});

	// ── Tool: prepare_scan ──────────────────────────────────────
	// Python 量化粗筛，使用 mootdx + AKShare 真实行情数据
	// 输出结构化 JSON 供 pi agent 做 LLM 判断
	pi.registerTool({
		name: "prepare_scan",
		label: "Prepare Scan Data",
		description:
			"执行 sagent 量化粗筛（真实行情）：股票池过滤 → 技术候选 → K 线描述 → 板块验证 → 持仓监控。不做 LLM 判断，输出结构化 JSON 供你分析。",
		promptSnippet: "准备 sagent 扫描数据，获取候选股和板块验证结果。",
		promptGuidelines: [
			"prepare_scan 输出的 candidates 包含 K 线描述和量化指标，你需要用 a-share-main-trend skill 对每个候选做判断。",
			"sectors 中 needs_llm=true 的板块需要你做 LLM 判断（主线/弱主线/非主线）。",
			"使用 prepare_scan 的输出时，必须提醒用户不构成投资建议。",
		],
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
			const result = await runPython(ctx.cwd, "prepare_scan.py", []);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	// ── Tool: apply_decision ────────────────────────────────────
	// 接收 pi agent 的判断结果，写入 portfolio + 推送飞书
	pi.registerTool({
		name: "apply_decision",
		label: "Apply Decision",
		description:
			"将你的板块和个股判断结果写入 portfolio.json，并可选推送飞书。输入 JSON 格式的判断结果。",
		promptSnippet: "把判断结果写入 sagent portfolio。",
		promptGuidelines: [
			"apply_decision 不会自动交易，只更新本地 portfolio.json。",
			"使用 apply_decision 时，必须提醒用户不构成投资建议。",
		],
		parameters: Type.Object({
			decisions: Type.String({ description: "JSON 字符串：判断结果数组" }),
			trade_date: Type.Optional(
				Type.String({ description: "交易日期 YYYY-MM-DD" }),
			),
			initial_cash: Type.Optional(
				Type.Number({
					description: "初始资金（新建 portfolio 时）",
					default: 100000,
				}),
			),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const args = ["--initial-cash", String(params.initial_cash ?? 100000)];
			if (params.trade_date) {
				args.push("--trade-date", params.trade_date);
			}
			const scriptPath = path.join(ctx.cwd, "scripts", "apply_decision.py");
			const result = await new Promise<{ stdout: string; stderr: string }>(
				(resolve, reject) => {
					const child = spawn(PYTHON, [scriptPath, ...args], {
						cwd: ctx.cwd,
						windowsHide: true,
					});
					let stdout = "";
					let stderr = "";
					child.stdout.on("data", (chunk: Buffer) => {
						stdout += chunk.toString("utf8");
					});
					child.stderr.on("data", (chunk: Buffer) => {
						stderr += chunk.toString("utf8");
					});
					child.on("close", (code) => {
						if (code !== 0)
							reject(new Error(`apply_decision exit ${code}: ${stderr}`));
						else resolve({ stdout: stdout.trim(), stderr: stderr.trim() });
					});
					child.stdin.write(params.decisions);
					child.stdin.end();
				},
			);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	// ── Tool: check_portfolio ───────────────────────────────────
	pi.registerTool({
		name: "check_portfolio",
		label: "Check Portfolio",
		description: "读取或初始化 sagent 本地 portfolio.json 持仓状态。",
		promptSnippet: "检查本地 portfolio.json 持仓状态。",
		parameters: Type.Object({
			init: Type.Optional(
				Type.Boolean({ description: "如果文件不存在，是否初始化" }),
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

	// ── Tool: analyze_stock ─────────────────────────────────────
	pi.registerTool({
		name: "analyze_stock",
		label: "Analyze Stock",
		description: "生成单只股票的 K 线自然语言描述（使用真实行情数据）。",
		promptSnippet: "把个股 K 线转成自然语言描述，供你判断形态。",
		parameters: Type.Object({
			symbol: Type.String({ description: "股票代码，例如 000001" }),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const result = await runPython(ctx.cwd, "analyze_stock.py", [
				"--symbol",
				params.symbol,
			]);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	// ── Tool: send_feishu_notification ──────────────────────────
	pi.registerTool({
		name: "send_feishu_notification",
		label: "Send Feishu Notification",
		description: "发送 sagent 飞书机器人通知。未配置 webhook 时安全跳过。",
		promptSnippet: "把 sagent 结果推送到飞书。",
		promptGuidelines: [
			"使用 send_feishu_notification 时，必须提醒用户不构成投资建议。",
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
			const result = await runPythonSafe(ctx.cwd, "notify_feishu.py", args);
			return {
				content: [{ type: "text", text: result.stdout }],
				details: { stderr: result.stderr, data: parseJson(result.stdout) },
			};
		},
	});

	// ── Command: /scan ──────────────────────────────────────────
	// pi agent 主导的完整扫描流程（真实行情）
	pi.registerCommand("scan", {
		description:
			"执行 sagent 每日扫描（真实行情）：量化粗筛 → LLM 判断 → 写入持仓 → 飞书推送",
		handler: async (_args, ctx) => {
			ctx.ui.notify("sagent /scan 开始：正在连接通达信获取真实行情...", "info");

			try {
				// Step 1: 量化粗筛（真实数据）
				const prepareResult = await runPython(ctx.cwd, "prepare_scan.py", []);
				const data = parseJson(prepareResult.stdout);

				// Step 2: 把结构化数据发给 pi agent，让 pi 用自身模型做判断
				const candidateSummaries = (data.candidates ?? [])
					.map(
						(c: any) =>
							`- ${c.symbol} ${c.name} | 板块: ${c.sector} | 关键低点: ${c.kline_key_low}\n  K线: ${c.kline_description}`,
					)
					.join("\n\n");

				const sectorSummaries = (data.sectors ?? [])
					.map(
						(s: any) =>
							`- ${s.sector}: ${s.level}${s.needs_llm ? " (需LLM判断)" : ""}`,
					)
					.join("\n");

				const portfolioInfo =
					data.portfolio?.positions?.length > 0
						? `持仓 ${data.portfolio.positions.length} 只，建议: ${JSON.stringify(data.portfolio.suggestions)}`
						: "无持仓";

				pi.sendMessage(
					{
						customType: "sagent-scan-ready",
						content: `# sagent 扫描数据已就绪

## 板块验证
${sectorSummaries}

## 候选股（${(data.candidates ?? []).length} 只）
${candidateSummaries || "无候选股"}

## 持仓状态
${portfolioInfo}

---

请使用 **a-share-main-trend** skill 对以上数据做判断：
1. 对 needs_llm 的板块判断主线/弱主线/非主线
2. 对每只候选股判断买入/观察/放弃，给出 key_low、止损价、无效条件
3. 判断完成后用 **apply_decision** tool 写入 portfolio

⚠️ 仅作研究和辅助分析，不构成投资建议。`,
						display: true,
						details: data,
					},
					{ triggerTurn: true, deliverAs: "nextTurn" },
				);
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`sagent /scan 失败：${message}`, "error");
			}
		},
	});
}
