import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppRoutes } from '@/App';
import type { LiveExperiment } from '@/api/schemas';
import type { Registry } from '@/api/types';

const SESSION = {
  identity: 'admin' as const,
  csrf_token: 'a'.repeat(64),
  expires_at: '2026-10-24T12:00:00Z',
};

const REGISTRY: Registry = {
  engines: [
    {
      id: 'ollama',
      name: 'Ollama',
      version: '1.0.0',
      build: 'cpu-test',
      availability: 'available',
      seed_supported: true,
    },
  ],
  models: [
    {
      id: 'llama',
      name: 'Llama test',
      parameter_size: '3B',
      revision: 'rev-test',
      sha256: '1'.repeat(64),
      quantization: 'Q4_K_M',
      engine_ids: ['ollama'],
      max_context_tokens: 4096,
      license_name: 'Test license',
    },
  ],
  workloads: [
    {
      id: 'work',
      prompt_id: 'prompt',
      sha256: '2'.repeat(64),
      data_policy: 'public',
      license_name: 'Test license',
    },
  ],
};

const UNKNOWN_WORKER = {
  availability: 'unknown',
  worker_id: 'unknown',
  observed_at: '2026-10-23T12:00:00Z',
  last_seen_at: null,
  mode: null,
  active_job_id: null,
  paused: false,
};

function makeExperiment(
  id = 'exp-test',
  name = 'Test run',
  job: Partial<LiveExperiment['job']> = {},
): LiveExperiment {
  return {
    id,
    name,
    version: 1,
    archived_at: null,
    config: {
      experiment_id: id,
      engine_id: 'ollama',
      engine_version: '1.0.0',
      engine_build: 'cpu-test',
      seed_supported: true,
      model_id: 'llama',
      model_revision: 'rev-test',
      model_sha256: '1'.repeat(64),
      quantization: 'Q4_K_M',
      workload_id: 'work',
      prompt_id: 'prompt',
      condition: 'warm',
      context_tokens: 4096,
      input_token_budget: 512,
      max_output_tokens: 256,
      sampling: { temperature: 0.2, top_p: 0.9, seed: null },
      warmups: 1,
      repetitions: 3,
      concurrency: 1,
      timeout_seconds: 300,
      gpu_device_id: 'gpu-0',
      gpu_layers: null,
    },
    job: {
      id: 'JOB-test',
      experiment_id: id,
      state: 'pending',
      phase: 'queued',
      attempt: 0,
      created_at: '2026-10-23T12:00:00Z',
      started_at: null,
      finished_at: null,
      error_code: null,
      cancellation_requested: false,
      ...job,
    },
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function apiError(status: number, code: string) {
  return json({ error: { code, message: 'Test error', request_id: 'request-test' } }, status);
}

interface FetchSetup {
  authenticated?: boolean;
  experiment?: LiveExperiment;
  worker?: unknown;
}

function installFetch({ authenticated = true, experiment, worker }: FetchSetup = {}) {
  let signedIn = authenticated;
  let created: LiveExperiment | null = null;
  const calls: Array<{ path: string; method: string; init: RequestInit; body: unknown }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url).pathname;
    const method = (init.method ?? 'GET').toUpperCase();
    let body: unknown = null;
    if (typeof init.body === 'string') body = JSON.parse(init.body) as unknown;
    calls.push({ path, method, init, body });

    if (path === '/api/v1/auth/session') {
      return signedIn ? json(SESSION) : apiError(401, 'unauthorized');
    }
    if (path === '/api/v1/auth/login' && method === 'POST') {
      signedIn = true;
      return json(SESSION);
    }
    if (path === '/api/v1/registry') return json(REGISTRY);
    if (path === '/api/v1/worker') return json(worker ?? UNKNOWN_WORKER);
    if (path === '/api/v1/experiments' && method === 'GET') {
      return json({ items: experiment ? [experiment] : [], next_cursor: null });
    }
    if (path === '/api/v1/experiments' && method === 'POST') {
      const request = body as {
        name: string;
        config: LiveExperiment['config'];
      };
      created = makeExperiment(request.config.experiment_id, request.name);
      return json(created, 202);
    }
    if (path.startsWith('/api/v1/experiments/') && method === 'GET') {
      return json(created ?? experiment ?? makeExperiment());
    }
    if (path.endsWith('/cancel') && method === 'POST') {
      const current = created ?? experiment ?? makeExperiment();
      return json({
        ...current,
        job: {
          ...current.job,
          state: 'running',
          phase: 'running',
          attempt: 1,
          started_at: '2026-10-23T12:00:01Z',
          cancellation_requested: true,
        },
      });
    }
    return apiError(404, 'not_found');
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls };
}

function renderAdmin(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('live admin console', () => {
  it('requires a session and signs in with the server CSRF contract', async () => {
    const user = userEvent.setup();
    const { calls } = installFetch({ authenticated: false });
    renderAdmin('/admin/experiments');

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible();
    await user.type(screen.getByLabelText('Admin password'), 'correct horse battery staple');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Experiments' })).toBeVisible();
    expect(await screen.findByText('No experiments yet')).toBeVisible();

    const login = calls.find(
      (call) => call.path === '/api/v1/auth/login' && call.method === 'POST',
    );
    expect(login?.body).toEqual({ password: 'correct horse battery staple' });
    expect(login?.init.credentials).toBe('include');
  });

  it('validates and queues a bounded config, then shows only accepted progress', async () => {
    const user = userEvent.setup();
    const { calls } = installFetch();
    renderAdmin('/admin/experiments/new');

    expect(await screen.findByRole('heading', { name: 'New experiment' })).toBeVisible();
    expect(await screen.findByText('Worker has not reported a heartbeat')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Queue experiment' }));
    expect(await screen.findByText(/1 field needs attention/)).toBeVisible();
    expect(screen.getByText('Enter an administrative name.')).toBeVisible();

    await user.type(screen.getByLabelText('Administrative name'), 'My test run');
    await user.click(screen.getByRole('button', { name: 'Queue experiment' }));

    expect(await screen.findByRole('heading', { name: 'My test run' })).toBeVisible();
    expect(await screen.findByText(/Submission accepted/)).toBeVisible();
    expect(screen.getByText(/has not started/)).toBeVisible();

    const create = calls.find(
      (call) => call.path === '/api/v1/experiments' && call.method === 'POST',
    );
    expect(create).toBeDefined();
    const headers = create?.init.headers as Record<string, string>;
    const request = create?.body as {
      idempotency_key: string;
      config: LiveExperiment['config'];
    };
    expect(headers['X-CSRF-Token']).toBe(SESSION.csrf_token);
    expect(headers['Idempotency-Key']).toBe(request.idempotency_key);
    expect(request.idempotency_key).toMatch(/^idem-/);
    expect(request.config).toMatchObject({
      engine_id: 'ollama',
      model_id: 'llama',
      workload_id: 'work',
      condition: 'warm',
      concurrency: 1,
      warmups: 1,
      repetitions: 3,
      gpu_device_id: 'gpu-0',
      gpu_layers: null,
      sampling: { temperature: 0.2, top_p: 0.9, seed: null },
    });
  });

  it('requests cooperative cancellation without claiming the job stopped', async () => {
    const user = userEvent.setup();
    const running = makeExperiment('exp-running', 'Running run', {
      state: 'running',
      phase: 'running',
      attempt: 1,
      started_at: '2026-10-23T12:00:01Z',
    });
    const { calls } = installFetch({
      experiment: running,
      worker: {
        availability: 'online',
        worker_id: 'worker-test',
        observed_at: '2026-10-23T12:00:10Z',
        last_seen_at: '2026-10-23T12:00:05Z',
        mode: 'running',
        active_job_id: running.job.id,
        paused: false,
      },
    });
    renderAdmin('/admin/experiments/exp-running');

    expect(await screen.findByRole('heading', { name: 'Running run' })).toBeVisible();
    expect(await screen.findByText('Worker online, running a job')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Cancel job' }));

    expect(await screen.findByText(/Waiting for worker acknowledgement/)).toBeVisible();
    expect(screen.getByText(/The worker has not acknowledged it yet/)).toBeVisible();

    const cancel = calls.find((call) => call.path.endsWith('/cancel'));
    expect(cancel?.method).toBe('POST');
    const headers = cancel?.init.headers as Record<string, string>;
    expect(headers['X-CSRF-Token']).toBe(SESSION.csrf_token);
    expect(headers['Idempotency-Key']).toMatch(/^idem-/);
  });
});
