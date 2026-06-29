/*
 * Live stats — a Vercel serverless function that reads directly from Amazon
 * DynamoDB (the project's primary datastore) and serves a live count to the
 * marketing site. This is the Vercel -> DynamoDB path: the front end is on
 * Vercel, the function runs on Vercel, and it queries DynamoDB at the edge.
 *
 * Caches at the Vercel edge for 30s (stale-while-revalidate) so a burst of
 * page loads does not hammer the table.
 *
 * Env (set in the Vercel project, read-only IAM key scoped to one table):
 *   AWS_REGION              us-east-1
 *   AWS_ACCESS_KEY_ID       AKIA... (read-only)
 *   AWS_SECRET_ACCESS_KEY   ...
 *   STATS_TABLE             solace-patients (optional, defaults below)
 *
 * `api/` is outside the Vite tsconfig, so Vercel compiles this with its own
 * Node toolchain. If creds are absent it returns a safe fallback, never 500s.
 */
import { DynamoDBClient, ScanCommand } from '@aws-sdk/client-dynamodb';

type Res = {
  status: (code: number) => Res;
  json: (data: unknown) => void;
  setHeader: (name: string, value: string) => void;
};

const TABLE = process.env.STATS_TABLE || 'solace-patients';

export default async function handler(_req: unknown, res: Res): Promise<void> {
  res.setHeader('Cache-Control', 's-maxage=30, stale-while-revalidate=300');
  res.setHeader('Content-Type', 'application/json');

  if (!process.env.AWS_ACCESS_KEY_ID) {
    res.status(200).json({ source: 'fallback', patientsTriaged: null, table: TABLE });
    return;
  }

  try {
    const ddb = new DynamoDBClient({ region: process.env.AWS_REGION || 'us-east-1' });
    const out = await ddb.send(new ScanCommand({ TableName: TABLE, Select: 'COUNT' }));
    res.status(200).json({
      source: 'dynamodb',
      table: TABLE,
      region: process.env.AWS_REGION || 'us-east-1',
      patientsTriaged: out.Count ?? 0,
    });
  } catch (err) {
    res.status(200).json({ source: 'error', patientsTriaged: null, table: TABLE, error: String((err as Error).message) });
  }
}
