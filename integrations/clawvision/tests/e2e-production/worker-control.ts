import { spawn, execFile, type ChildProcess } from 'node:child_process';
import { promisify } from 'node:util';
import { resolve, join } from 'node:path';
import { mkdirSync, openSync, closeSync } from 'node:fs';

const run = promisify(execFile);

// Owns only the isolated acceptance Worker. External mode requires an explicitly
// named Compose project using the acceptance override, never a deployed Worker.
export class AcceptanceWorker {
  private child?: ChildProcess;
  private log?: number;
  private async compose(...args: string[]) {
    const project = process.env.CLAWVISION_E2E_COMPOSE_PROJECT;
    if (!project) throw new Error('Recovery acceptance requires an isolated CLAWVISION_E2E_COMPOSE_PROJECT');
    await run('docker', ['compose', '-p', project, '-f', 'docker-compose.yml', '-f', 'compose.e2e.yml', ...args], { windowsHide: true });
  }
  async start() {
    if (process.env.CLAWVISION_E2E_BASE_URL) { await this.compose('up', '-d', 'worker'); return; }
    const directory = process.env.CLAWVISION_E2E_DATA_DIR;
    if (!directory) throw new Error('Acceptance data directory is not configured');
    mkdirSync(directory, { recursive: true });
    this.log = openSync(join(directory, 'worker.log'), 'a');
    this.child = spawn(process.env.CLAWVISION_E2E_PYTHON ?? 'python', ['workers/task_worker.py'], {
      cwd: process.cwd(), windowsHide: true, detached: process.platform !== 'win32', stdio: ['ignore', this.log, this.log],
      env: { ...process.env, DATABASE_URL: '', ARTIFACT_STORE: 'local', CLAWVISION_AUTH_MODE: 'enabled', CLAWVISION_EMBEDDED_WORKERS: 'false',
        CLAWVISION_DATA_DIR: directory, CLAWVISION_OBJECT_DIR: join(directory, 'objects'), CLAWVISION_WORKER_METRICS_PORT: '0',
        CLAWVISION_WORKER_ID: `acceptance-${Date.now()}`, CLAWVISION_WORKER_LEASE_SECONDS: '5', CLAWVISION_TRAINING_SCRIPT: resolve('tests/fixtures/training_recovery.py') },
    });
    this.child.on('error', () => {}); // Startup failure is surfaced by job/lease assertions and retained logs.
  }
  async kill() {
    if (process.env.CLAWVISION_E2E_BASE_URL) { await this.compose('kill', '-s', 'SIGKILL', 'worker'); return; }
    if (this.child?.pid && this.child.exitCode === null) {
      const exited = new Promise<void>((done) => this.child!.once('exit', () => done()));
      if (process.platform === 'win32') await run('taskkill', ['/PID', String(this.child.pid), '/T', '/F'], { windowsHide: true });
      else process.kill(-this.child.pid, 'SIGKILL');
      await exited;
    }
    this.child = undefined;
    if (this.log !== undefined) { closeSync(this.log); this.log = undefined; }
  }
}
