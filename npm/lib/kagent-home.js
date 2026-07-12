"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.resolveKagentHome = resolveKagentHome;
exports.kagentStatePath = kagentStatePath;
exports.kagentCachePath = kagentCachePath;
const node_path_1 = __importDefault(require("node:path"));
function requiredHome(env) {
    const home = env.HOME;
    if (!home) {
        throw new Error("HOME is required to resolve the kagent home directory");
    }
    return home;
}
function resolveKagentHome(env = process.env) {
    const configured = env.KAGENT_HOME;
    if (!configured) {
        return node_path_1.default.resolve(requiredHome(env), ".kagent");
    }
    if (configured === "~") {
        return node_path_1.default.resolve(requiredHome(env));
    }
    if (configured.startsWith("~/") || configured.startsWith("~\\")) {
        return node_path_1.default.resolve(requiredHome(env), configured.slice(2));
    }
    return node_path_1.default.resolve(configured);
}
function kagentStatePath(name, env = process.env) {
    return node_path_1.default.join(resolveKagentHome(env), "state", name);
}
function kagentCachePath(name, env = process.env) {
    return node_path_1.default.join(resolveKagentHome(env), "cache", name);
}
