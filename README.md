# MarkItDown API Service

This project provides a REST API wrapper for Microsoft's [MarkItDown](https://github.com/microsoft/markitdown) library, which converts various file formats to Markdown.

## Features

- REST API for document conversion
- Asynchronous processing with job status tracking
- Kubernetes deployment ready
- Easily integrates with NestJS applications

## Local Development

### Prerequisites

- Docker
- Python 3.10+
- FastAPI
- MarkItDown

### Building the Docker Image

```bash
docker build -t markitdown-api:latest .
```

### Running Locally

```bash
docker run -p 8000:8000 markitdown-api:latest
```

The API will be available at http://localhost:8000

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster
- kubectl configured to access your cluster
- Container registry access

### Deployment Steps

1. Update the image path in `k8s/deployment.yaml` to match your registry
2. Push the Docker image to your registry
3. Apply the Kubernetes configuration:

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

## Automated Deployment with GitHub Actions

This repository includes GitHub Actions workflows for automated deployment to Kubernetes clusters. The deployment process is configured to work with both staging and production environments.

### GitHub Actions Workflow

The deployment workflow is defined in `.github/workflows/deploy.yml` and supports:

- Automatic deployment on pushes to `main` (production) and `staging` branches
- Manual deployment via GitHub Actions workflow dispatch
- Environment-specific configuration via GitHub repository variables

### Configuration Variables

The following variables can be configured in your GitHub repository settings:

| Variable | Description | Default Value |
|----------|-------------|---------------|
| APP_NAME | Application name | markitdown-api |
| REGISTRY | Container registry URL | lax.vultrcr.com |
| REGISTRY_PATH | Path within registry | pretuned/markitdown-api |
| K8S_NAMESPACE | Kubernetes namespace | default |
| REPLICAS | Number of replicas | 2 (staging), 3 (production) |
| DOMAIN | Public domain | staging-markitdown-api.pretuned.ai (staging), markitdown-api.pretuned.ai (production) |
| MEMORY_REQUEST | Memory request | 256Mi |
| MEMORY_LIMIT | Memory limit | 512Mi |
| CPU_REQUEST | CPU request | 100m |
| CPU_LIMIT | CPU limit | 500m |
| PULL_SECRET_NAME | Image pull secret name | vultr-registry |

### Required Secrets

The following secrets must be configured in your GitHub repository:

- `DOCKER_USERNAME`: Username for container registry authentication
- `DOCKER_PASSWORD`: Password for container registry authentication
- `KUBE_CONFIG`: Kubernetes configuration file content (base64 encoded)
- `REPO_ACCESS_TOKEN`: GitHub token with repository access (for cross-repo triggers)

### Integration with Backend API

The MarkItDown API is designed to be deployed as a microservice alongside the main backend API. The backend API is configured to communicate with the MarkItDown service using the following environment variable:

```
MARKITDOWN_URL=http://markitdown-api.default.svc.cluster.local
```

This URL is automatically configured in the backend API's deployment process.

## API Endpoints

- `GET /health` - Health check endpoint
- `POST /convert` - Convert a file to Markdown
- `GET /status/{job_id}` - Check conversion job status

## Integration with NestJS

The NestJS integration module is available in the `pretuned__backend-api` project under:
`src/api/v1/modules/document-converter`

### Environment Configuration

Add the following to your `.env` file:

```
MARKITDOWN_URL=http://markitdown-service
```

For local development, you can set this to `http://localhost:8000` if running the MarkItDown API locally.

## Usage Example

```typescript
// In your NestJS service
import { DocumentConverterService } from '../document-converter';

@Injectable()
export class YourService {
  constructor(private readonly documentConverterService: DocumentConverterService) {}

  async processDocument(filePath: string) {
    const result = await this.documentConverterService.convertToMarkdown(filePath);
    // Use the markdown content
    console.log(result.markdown);
    return result;
  }
}
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
