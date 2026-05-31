import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const execFileAsync = promisify(execFile);

async function runPython(cwd: string, script: string, args: string[] = []) {
  const scriptPath = path.join(cwd, "scripts", script);
  const { stdout, stderr } = await execFileAsync("python", [scriptPath, ...args], {
    cwd,
    encoding: "utf8",
    windowsHide: true,
  });

  return {
    stdout: stdout.trim(),
    stderr: stderr.trim(),
  };
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
      mock: Type.Optional(Type.Boolean({ description: "是否强制使用 mock 数据" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const args = params.mock === false ? [] : ["--mock"];
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
      init: Type.Optional(Type.Boolean({ description: "如果文件不存在，是否初始化 portfolio.json" })),
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
    name: "analyze_stock",
    label: "Analyze Stock",
    description: "生成单只股票的 K 线自然语言描述。骨架阶段返回 mock 描述。",
    promptSnippet: "把个股 K 线转成自然语言描述，供 GLM5.1 判断形态。",
    parameters: Type.Object({
      symbol: Type.String({ description: "股票代码，例如 000001" }),
      mock: Type.Optional(Type.Boolean({ description: "是否强制使用 mock 数据" })),
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
    description: "执行一次 sagent 每日收盘后扫描（当前为骨架 mock 流程）",
    handler: async (_args, ctx) => {
      try {
        const result = await runPython(ctx.cwd, "market_scan.py", ["--mock"]);
        ctx.ui.notify("sagent /scan 已完成（mock）", "info");
        pi.sendMessage(
          {
            customType: "sagent-scan-result",
            content: `# sagent 扫描结果（mock）\n\n\`\`\`json\n${result.stdout}\n\`\`\`\n\n当前仅为项目骨架，尚未接入真实 AKShare 数据，不构成投资建议。`,
            display: true,
            details: { stderr: result.stderr, data: parseJson(result.stdout) },
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
