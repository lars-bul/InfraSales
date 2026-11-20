// The session check's answers for the sample users: alice (admin), vera (viewer), nobody.
export const alice = { subject: "basic:alice", name: "alice", role: "admin" } as const;
export const vera = { subject: "basic:vera", name: "vera", role: "viewer" } as const;

export const anonymous = { body: { user: null, provider: "basic" } };

export function signedIn(user: typeof alice | typeof vera) {
  return { body: { user, provider: "basic" } };
}
