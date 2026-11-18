/** Memory only. Every reuse is validated by an authenticated version request. */
interface Result<T> { data: T; version: string | null }
interface Entry extends Result<unknown> { expires: number; size: number }

export class ReadCache {
  private entries = new Map<string, Entry>();
  private pending = new Map<string, Promise<unknown>>();
  private validation: Promise<string | null> | null = null;
  private knownVersion: string | null | undefined;
  private epoch = 0;
  private size = 0;

  constructor(
    private version: () => Promise<string | null>,
    private clock = () => Date.now(),
    private ttl = 30_000,
    private maxEntries = 40,
    private maxSize = 5_000_000,
  ) {}

  clear() {
    this.epoch++;
    this.entries.clear();
    this.pending.clear();
    this.validation = null;
    this.knownVersion = undefined;
    this.size = 0;
  }

  private assertSession(epoch: number) {
    if (epoch !== this.epoch) throw new Error("Your session changed. Please reload the page.");
  }

  private remove(key: string) {
    this.size -= this.entries.get(key)?.size ?? 0;
    this.entries.delete(key);
  }

  private validate(): Promise<string | null> {
    if (this.validation) return this.validation;
    const epoch = this.epoch;
    const promise = this.version().then((version) => {
      this.assertSession(epoch);
      this.knownVersion = version;
      for (const [key, entry] of this.entries) {
        if (version === null || entry.version !== version) this.remove(key);
      }
      return version;
    }).finally(() => {
      if (this.validation === promise) this.validation = null;
    });
    this.validation = promise;
    return promise;
  }

  read<T>(key: string, load: () => Promise<Result<T>>): Promise<T> {
    const existing = this.pending.get(key);
    if (existing) return existing.then((data) => structuredClone(data) as T);
    const epoch = this.epoch;
    const promise = this.load(key, load, epoch).catch((error) => {
      // Never fall back to a possibly outdated price after a failed check.
      if (epoch === this.epoch) this.remove(key);
      throw error;
    }).finally(() => {
      if (this.pending.get(key) === promise) this.pending.delete(key);
    });
    this.pending.set(key, promise);
    return promise.then((data) => structuredClone(data));
  }

  private async load<T>(key: string, load: () => Promise<Result<T>>, epoch: number): Promise<T> {
    const cached = this.entries.get(key);
    if (cached && this.clock() < cached.expires) {
      const version = await this.validate();
      this.assertSession(epoch);
      if (version !== null && cached.version === version) {
        this.entries.delete(key);
        this.entries.set(key, cached);
        return cached.data as T;
      }
    }
    this.remove(key);
    for (let attempt = 0; attempt < 3; attempt++) {
      const result = await load();
      this.assertSession(epoch);
      if (result.version && this.knownVersion !== undefined && result.version !== this.knownVersion) {
        // A slower response must not replace a version already seen elsewhere.
        const current = await this.validate();
        this.assertSession(epoch);
        if (current !== null && result.version !== current) continue;
        if (current === null) return result.data;
      }
      if (result.version) {
        const size = JSON.stringify(result.data).length;
        if (size <= this.maxSize) {
          this.entries.set(key, { ...result, expires: this.clock() + this.ttl, size });
          this.size += size;
          while (this.entries.size > this.maxEntries || this.size > this.maxSize) {
            this.remove(this.entries.keys().next().value!);
          }
        }
      }
      return result.data;
    }
    throw new Error("New data is arriving. Please try again in a moment.");
  }
}
