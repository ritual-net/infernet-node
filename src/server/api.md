# API Documentation

## Endpoints

#### 1. GET `/info`

Retrieves information about the containers running on this node, and the number of jobs pending.

- **Method:** `GET`
- **URL:** `/info`
- **Response:**
  - **Success:**
    - **Code:** `200 OK`
    - **Content:**
      ```json
      {
        "containers": Container[],
        "pending": {
          "offchain": integer,
          "onchain": integer
        }
      }
      ```
      - `containers`: Array of [Container](#container) objects
      - `pending`: Job counts
        - `offchain`: Offchain jobs pending
        - `onchain`: Onchain jobs pending
---

#### 2a. POST `/api/jobs`

Creates a new off-chain job (direct compute request or subscription).

- **Method:** `POST`
- **URL:** `/api/jobs`
- **Body:** [JobRequest](#jobrequest)
- **Response:**
  - **Success:**
    - **Code:** `200 OK`
    - **Content:**
    `{ "id": string }`
      - `id`: UUID of the created job.
  - **Failure:**
    - **Code:** `400 Bad Request`
    - **Content:**
        `{ "error": string[, "params": object] }`
      - `error`: Error message
      - `params`: Additional error parameters (if applicable).


#### 2b. POST `/api/jobs/batch`

Creates off-chain jobs in batch (direct compute requests or subscriptions).

NOTE: Individual job requests **fail silently** in batch mode, i.e. this endpoint might
return `200 OK` even if subset / all job requests fail. It is the **caller's** responsibility to check
the returned array for errors in creating jobs.

- **Method:** `POST`
- **URL:** `/api/jobs/batch`
- **Body:** [JobRequest](#jobrequest)[]
- **Response:**
  - **Success:**
    - **Code:** `200 OK`
    - **Content:**
    `{ "id": string } | { "error": string[, "params": object] } []`
      - Array of job UUID or error for each JobRequest **in order**, depending on successful creation.
  - **Failure:**
    - **Code:** `400 Bad Request`
    - **Content:**
        `{ "error": string[, "params": object] }`
      - `error`: Error message
      - `params`: Additional error parameters (if applicable).

---

#### 3. GET `/api/jobs`

Retrieves specific job results based on one or more provided job IDs. If the id query parameter is not provided, returns a list of job IDs for the client. Optionally filters by `pending` status.

- **Method:** `GET`
- **URL:** `/api/jobs`
- **Query Parameters:**
  - `id` (`string`, optional, repeatable): Job UUID(s). If provided, the endpoint returns the status of the specific job(s). Multiple job IDs can be specified by repeating this parameter (e.g., `?id=123&id=456`). If omitted, the endpoint returns a list of job IDs for the given client.
  - `intermediate` (`boolean`, optional): Only used if `id` is provided. Flag for returning intermediate results. Applies to all specified jobs
  - `pending` (`boolean`, optional): Only used if `id` is omitted. Flag to specify whether to fetch pending (`true`), finished (`false`), or all jobs (omit).
- **Response:**
  - **Success:**
    - **Code:** `200 OK`
    - **Content:**
      - If `id` is provided: [JobResult](#jobresult)[]
        - If `intermediate=true`, includes intermediate results.
      - If `id` is not provided: An array of job IDs (`string[]`)
        - If `pending=true`, only returns pending jobs.
        - If `pending=false`, only returns finished jobs.
        - If `pending` is omitted, returns all jobs.
  - **Failure:**
    - **Code:** `400 Bad Request` / `404 Not Found`
    - **Content:** `{ "error": string }`
      - `error`: Error message

---

#### 4. PUT `/api/status`

> **Warning: DO NOT USE THIS ENDPOINT IF YOU DON'T KNOW WHAT YOU'RE DOING.**
> This endpoint is meant to be used by containers that do **NOT** comply with Infernet, but still want to use it to record job IDs and statuses. This could be useful in the case of legacy images, where achieving [Infernet compatibility](https://docs.ritual.net/infernet/node/containers) is impractical.

Registers job ID and status with the node.

- **Method:** `PUT`
- **URL:** `/api/status`
- **Body:**
  ```json
    {
      "id": string,
      "status": "success" | "failed" | "running"
      "containers": string[]
    }
  ```
  - `id`: ID of the job
  - `status`: Status of the job
  - `containers`: IDs of container(s) to associate with the job
- **Response:**
  - **Success:**
    - **Code:** `200 OK`
  - **Failure:**
    - **Code:** `400 Bad Request`
    - **Content:**
        `{ "error": string }`
      - `error`: Error message
      - `params`: Additional error parameters (if applicable).

---

## Data Types

#### JobRequest

Specifies a job, which consists of running one or more containers. If more than one container is specified, output of container `i` is input to container `i+1`; `containers[0]` takes `data` as input; and `containers[n-1]`'s output is the result of the job.

- **containers** (`string[]`) - Array of container IDs to run in sequence.
- **data** (`object`) - The input data to be passed into `containers[0]`.

```json
{
    "containers": string[],
    "data": object
}
```


#### JobResult

- **id**: Job UUID.
- **status**: `"running"`, `"success"`, or `"failed"`.
- **result**: [ContainerResult](#containerresult)
- **intermediate**: Array of [ContainerResults](#containerresult). Optional.

```json
{
    "id": string,
    "status": string,
    "result": ContainerResult,
    "intermediate_results": ContainerResult[]
}
```

#### Container

Represents a containerized workload running on the node.

- **id** (`string`) - ID of the container.
- **external** (`boolean`) - Whether the container is external, i.e. `true` if container can be the first container in [JobRequest](#jobrequest).containers.
- **image** (`string`) - The DockerHub image this container is running.
- **description** (`string`, optional) - Description of the containerized workload.

```json
{
  "id": string,
  "external": boolean,
  "image": string,
  "description": string
}
```

#### ContainerOutput

Represents the output data of a [container](#container).

- **container** (`string`) - ID of the container.
- **output** (`object`) - The output data, structure depends on the container.

```json
{
  "container": string,
  "output": object
}
```

#### ContainerError

Represents the output error of a [container](#container).

- **container** (`string`) - ID of the container.
- **error** (`string`) - The error message from the container.

```json
{
  "container": string,
  "error": string
}
```

#### ContainerResult

[ContainerOutput](#containeroutput) or [ContainerError](#containererror).
