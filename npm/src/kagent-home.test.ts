import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  kagentCachePath,
  kagentStatePath,
  resolveKagentHome,
} from "./kagent-home";

test("defaults to the .kagent directory beneath HOME", () => {
  assert.equal(
    resolveKagentHome({ HOME: path.join(path.sep, "Users", "kaka") }),
    path.join(path.sep, "Users", "kaka", ".kagent"),
  );
});

test("expands a tilde-prefixed KAGENT_HOME and makes relative overrides absolute", () => {
  const home = path.join(path.sep, "Users", "kaka");
  assert.equal(
    resolveKagentHome({ HOME: home, KAGENT_HOME: "~/shared-kagent" }),
    path.join(home, "shared-kagent"),
  );
  assert.equal(
    resolveKagentHome({ HOME: home, KAGENT_HOME: "relative-kagent" }),
    path.resolve("relative-kagent"),
  );
});

test("builds state and cache paths beneath the resolved kagent home", () => {
  const env = { KAGENT_HOME: path.join(path.sep, "srv", "kagent") };
  assert.equal(
    kagentStatePath("pending-approvals", env),
    path.join(path.sep, "srv", "kagent", "state", "pending-approvals"),
  );
  assert.equal(
    kagentCachePath("npm-python", env),
    path.join(path.sep, "srv", "kagent", "cache", "npm-python"),
  );
});

test("fails clearly when HOME is required but missing", () => {
  assert.throws(() => resolveKagentHome({}), /HOME.*required/i);
  assert.throws(
    () => resolveKagentHome({ KAGENT_HOME: "~/shared-kagent" }),
    /HOME.*required/i,
  );
});
