// A person's pseudonymous subject ("basic:alice", "oidc:a1b2c3") as the pages show it: without
// the sign-in provider's prefix, which tells nobody anything about who it was.
export function personOf(subject: string): string {
  return subject.slice(subject.indexOf(":") + 1);
}
