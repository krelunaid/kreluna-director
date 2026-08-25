export class GatewayError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | undefined;

  constructor(status: number, code: string, message: string, retryAfter?: number) {
    super(message);
    this.name = "GatewayError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}
