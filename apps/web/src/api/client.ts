import { z } from 'zod';
import {
  errorEnvelopeSchema,
  experimentPageSchema,
  experimentResourceSchema,
  registrySchema,
  sessionInfoSchema,
  workerHeartbeatSchema,
  type LiveExperiment,
  type LiveExperimentPage,
  type SessionInfo,
  type WorkerStatus,
} from './schemas';
import type { ExperimentConfig, Registry } from './types';

const DEFAULT_BASE_URL = 'https://127.0.0.1:8000';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(message: string, status: number, code: string, requestId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export function friendlyApiMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'An unexpected error occurred. Try again.';
  const byCode: Record<string, string> = {
    invalid_credentials: 'The password is incorrect.',
    login_locked: 'Too many failed sign-ins. Wait 15 minutes before trying again.',
    https_required: 'The local API requires trusted HTTPS. Open the console from its HTTPS origin.',
    invalid_origin:
      'This console origin is not allowed. Set INFERLAB_CONSOLE_ORIGIN to this exact HTTPS origin.',
    invalid_csrf: 'The security token expired. Reload the page and sign in again.',
    unauthorized: 'Your admin session expired. Sign in again.',
    auth_not_configured:
      'The admin password hash is not provisioned. Set INFERLAB_ADMIN_PASSWORD_HASH and restart the API.',
    database_not_configured:
      'The API has no database URL. Set INFERLAB_DATABASE_URL and restart the API.',
    database_not_ready: 'The database is not migrated. Run alembic upgrade head.',
    runner_not_configured:
      'No operator runner is configured, so the registry and submissions are unavailable.',
    storage_unavailable: 'The database is temporarily busy. Retry with the same request.',
    storage_conflict: 'The database rejected a conflicting write. Refresh and retry.',
    mutation_limit: 'The admin mutation limit was reached. Wait a minute before retrying.',
    admission_limit: 'The queue or daily submission limit was reached. Wait before retrying.',
    experiment_exists: 'That experiment ID is already reserved. Choose a different ID.',
    version_conflict: 'This experiment changed in another tab. Refresh before retrying.',
    job_active: 'Cancel the active job and wait for the worker to acknowledge it before archiving.',
    invalid_transition: 'This action is not valid for the current job state. Refresh the record.',
    idempotency_conflict:
      'This request key belongs to a different submission. Review the form and submit again.',
    invalid_idempotency_key: 'The idempotency key is invalid. Reload the form and try again.',
    unapproved_config:
      'The selected pins or settings are not approved by the local runner. Check the registry and hardware fields.',
    validation_error: 'Some fields are invalid. Review the highlighted values.',
    not_found: 'The requested record was not found.',
    invalid_response:
      'The API response did not match the console contracts. Check that the web and API versions match.',
    network_error:
      'Cannot reach the local API. Confirm it is running with trusted local HTTPS on this machine.',
    internal_error: 'The API hit an unexpected error. Check the server log and retry.',
  };
  return byCode[error.code] ?? error.message;
}

export interface ExperimentListParams {
  cursor?: string | null;
  limit?: number;
}

export interface CreateExperimentRequest {
  name: string;
  idempotency_key: string;
  config: ExperimentConfig;
}

interface ClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

export function createApiClient({ baseUrl, fetchImpl }: ClientOptions = {}) {
  const root = (baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(
    /\/+$/,
    '',
  );
  const doFetch = fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));

  async function request<T>(
    path: string,
    parse: z.ZodType<T>,
    options: {
      method?: string;
      body?: unknown;
      csrf?: string;
      idempotencyKey?: string;
      signal?: AbortSignal | undefined;
    } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (options.csrf) headers['X-CSRF-Token'] = options.csrf;
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;

    let response: Response;
    try {
      response = await doFetch(`${root}${path}`, {
        method: options.method ?? 'GET',
        credentials: 'include',
        headers,
        ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
        ...(options.signal ? { signal: options.signal } : {}),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError(
        friendlyApiMessage(new ApiError('', 0, 'network_error')),
        0,
        'network_error',
      );
    }

    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text) as unknown;
      } catch {
        throw new ApiError(
          friendlyApiMessage(new ApiError('', response.status, 'invalid_response')),
          response.status,
          'invalid_response',
        );
      }
    }

    if (!response.ok) {
      const parsed = errorEnvelopeSchema.safeParse(payload);
      const code = parsed.success ? parsed.data.error.code : 'internal_error';
      const requestId = parsed.success ? parsed.data.error.request_id : null;
      throw new ApiError(
        friendlyApiMessage(new ApiError('', response.status, code)),
        response.status,
        code,
        requestId,
      );
    }

    if (response.status === 204) return parse.parse(null);
    if (payload === null) {
      throw new ApiError(
        friendlyApiMessage(new ApiError('', response.status, 'invalid_response')),
        response.status,
        'invalid_response',
      );
    }
    const result = parse.safeParse(payload);
    if (!result.success) {
      throw new ApiError(
        friendlyApiMessage(new ApiError('', response.status, 'invalid_response')),
        response.status,
        'invalid_response',
      );
    }
    return result.data;
  }

  return {
    baseUrl: root,
    getSession: (signal?: AbortSignal) =>
      request('/api/v1/auth/session', sessionInfoSchema, { signal }),
    login: (password: string, signal?: AbortSignal) =>
      request('/api/v1/auth/login', sessionInfoSchema, {
        method: 'POST',
        body: { password },
        signal,
      }),
    logout: (csrf: string) => request('/api/v1/auth/logout', z.null(), { method: 'POST', csrf }),
    getRegistry: (signal?: AbortSignal): Promise<Registry> =>
      request('/api/v1/registry', registrySchema, { signal }),
    getWorker: (signal?: AbortSignal): Promise<WorkerStatus> =>
      request('/api/v1/worker', workerHeartbeatSchema, { signal }),
    listExperiments: (params: ExperimentListParams = {}, signal?: AbortSignal) => {
      const search = new URLSearchParams();
      search.set('limit', String(params.limit ?? 50));
      if (params.cursor) search.set('cursor', params.cursor);
      return request(`/api/v1/experiments?${search.toString()}`, experimentPageSchema, {
        signal,
      });
    },
    getExperiment: (id: string, signal?: AbortSignal) =>
      request(`/api/v1/experiments/${encodeURIComponent(id)}`, experimentResourceSchema, {
        signal,
      }),
    createExperiment: (body: CreateExperimentRequest, csrf: string) =>
      request('/api/v1/experiments', experimentResourceSchema, {
        method: 'POST',
        body,
        csrf,
        idempotencyKey: body.idempotency_key,
      }),
    renameExperiment: (id: string, name: string, version: number, csrf: string, key: string) =>
      request(`/api/v1/experiments/${encodeURIComponent(id)}`, experimentResourceSchema, {
        method: 'PATCH',
        body: { name, expected_version: version },
        csrf,
        idempotencyKey: key,
      }),
    archiveExperiment: (id: string, version: number, csrf: string, key: string) =>
      request(`/api/v1/experiments/${encodeURIComponent(id)}`, experimentResourceSchema, {
        method: 'DELETE',
        body: { expected_version: version },
        csrf,
        idempotencyKey: key,
      }),
    cancelExperiment: (id: string, csrf: string, key: string) =>
      request(`/api/v1/experiments/${encodeURIComponent(id)}/cancel`, experimentResourceSchema, {
        method: 'POST',
        csrf,
        idempotencyKey: key,
      }),
    retryExperiment: (id: string, csrf: string, key: string) =>
      request(`/api/v1/experiments/${encodeURIComponent(id)}/retry`, experimentResourceSchema, {
        method: 'POST',
        csrf,
        idempotencyKey: key,
      }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
export const apiClient = createApiClient();
export type { LiveExperiment, LiveExperimentPage, SessionInfo, WorkerStatus };
