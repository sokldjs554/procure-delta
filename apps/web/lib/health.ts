export type ApiStatus = "Available" | "Unavailable";

type HealthFetcher = (input: string, init?: RequestInit) => Promise<Response>;

export async function getApiStatus(
  apiUrl: string,
  fetchHealth: HealthFetcher = fetch,
): Promise<ApiStatus> {
  try {
    const response = await fetchHealth(`${apiUrl}/health/live`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    return response.ok ? "Available" : "Unavailable";
  } catch {
    return "Unavailable";
  }
}
