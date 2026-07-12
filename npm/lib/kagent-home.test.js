"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_path_1 = __importDefault(require("node:path"));
const node_test_1 = __importDefault(require("node:test"));
const kagent_home_1 = require("./kagent-home");
(0, node_test_1.default)("defaults to the .kagent directory beneath HOME", () => {
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: node_path_1.default.join(node_path_1.default.sep, "Users", "kaka") }), node_path_1.default.join(node_path_1.default.sep, "Users", "kaka", ".kagent"));
});
(0, node_test_1.default)("expands a tilde-prefixed KAGENT_HOME and makes relative overrides absolute", () => {
    const home = node_path_1.default.join(node_path_1.default.sep, "Users", "kaka");
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: home, KAGENT_HOME: "~/shared-kagent" }), node_path_1.default.join(home, "shared-kagent"));
    strict_1.default.equal((0, kagent_home_1.resolveKagentHome)({ HOME: home, KAGENT_HOME: "relative-kagent" }), node_path_1.default.resolve("relative-kagent"));
});
(0, node_test_1.default)("builds state and cache paths beneath the resolved kagent home", () => {
    const env = { KAGENT_HOME: node_path_1.default.join(node_path_1.default.sep, "srv", "kagent") };
    strict_1.default.equal((0, kagent_home_1.kagentStatePath)("pending-approvals", env), node_path_1.default.join(node_path_1.default.sep, "srv", "kagent", "state", "pending-approvals"));
    strict_1.default.equal((0, kagent_home_1.kagentCachePath)("npm-python", env), node_path_1.default.join(node_path_1.default.sep, "srv", "kagent", "cache", "npm-python"));
});
(0, node_test_1.default)("fails clearly when HOME is required but missing", () => {
    strict_1.default.throws(() => (0, kagent_home_1.resolveKagentHome)({}), /HOME.*required/i);
    strict_1.default.throws(() => (0, kagent_home_1.resolveKagentHome)({ KAGENT_HOME: "~/shared-kagent" }), /HOME.*required/i);
});
