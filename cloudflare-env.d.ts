declare namespace Cloudflare {
  interface Env {
    ADMIN_EMAIL?: string;
    DB?: D1Database;
    BUCKET?: R2Bucket;
  }
}
