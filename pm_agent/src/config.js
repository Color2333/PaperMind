// 凭据存取（E3）：与 Python 版 pm 完全兼容的同一文件
// ~/.config/papermind/config.toml（server_url/token/client_name，0600）。
// PaperMind token 与本地模型 provider 凭据分开保存——本文件只存 PaperMind 凭据。
import { chmod, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export function configDir() {
	return process.env.PAPERMIND_CONFIG_DIR || join(homedir(), ".config", "papermind");
}

export function configFile() {
	return join(configDir(), "config.toml");
}

/** 读取凭据；缺失/损坏返回 null */
export async function loadConfig() {
	let text;
	try {
		text = await readFile(configFile(), "utf8");
	} catch {
		return null;
	}
	const values = {};
	for (const line of text.split("\n")) {
		const trimmed = line.trim();
		if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
		const idx = trimmed.indexOf("=");
		const key = trimmed.slice(0, idx).trim();
		let raw = trimmed.slice(idx + 1).trim();
		if (raw.startsWith('"') && raw.endsWith('"')) raw = raw.slice(1, -1);
		values[key] = raw;
	}
	if (!values.server_url || !values.token) return null;
	return {
		serverUrl: values.server_url.replace(/\/+$/, ""),
		token: values.token,
		clientName: values.client_name || "pm-cli",
	};
}

/** 写入凭据（0600；令牌是敏感凭证） */
export async function saveConfig({ serverUrl, token, clientName = "pm-cli" }) {
	await mkdir(configDir(), { recursive: true });
	const path = configFile();
	const content =
		"# PaperMind CLI 配置（pm login 生成）\n" +
		`server_url = "${serverUrl.replace(/\/+$/, "")}"\n` +
		`token = "${token}"\n` +
		`client_name = "${clientName}"\n`;
	await writeFile(path, content, "utf8");
	await chmod(path, 0o600);
	return path;
}

export async function clearConfig() {
	await rm(configFile(), { force: true });
}

/** 解析优先级：显式参数 > 环境变量 > 配置文件（与 Python 版一致） */
export async function resolveServerUrl(explicit) {
	if (explicit) return explicit.replace(/\/+$/, "");
	if (process.env.PAPERMIND_SERVER_URL) return process.env.PAPERMIND_SERVER_URL.replace(/\/+$/, "");
	const cfg = await loadConfig();
	return cfg ? cfg.serverUrl : null;
}

export async function resolveToken() {
	if (process.env.PAPERMIND_TOKEN) return process.env.PAPERMIND_TOKEN;
	const cfg = await loadConfig();
	return cfg ? cfg.token : null;
}
