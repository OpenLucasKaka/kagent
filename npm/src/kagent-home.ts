import path from "node:path";

function requiredHome(env: NodeJS.ProcessEnv): string {
  const home = env.HOME;
  if (!home) {
    throw new Error("HOME is required to resolve the kagent home directory");
  }
  return home;
}

export function resolveKagentHome(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const configured = env.KAGENT_HOME;
  if (!configured) {
    return path.resolve(requiredHome(env), ".kagent");
  }
  if (configured === "~") {
    return path.resolve(requiredHome(env));
  }
  if (configured.startsWith("~/") || configured.startsWith("~\\")) {
    return path.resolve(requiredHome(env), configured.slice(2));
  }
  return path.resolve(configured);
}

export function kagentStatePath(
  name: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return path.join(resolveKagentHome(env), "state", name);
}

export function kagentCachePath(
  name: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  return path.join(resolveKagentHome(env), "cache", name);
}
