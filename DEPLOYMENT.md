# MarkItDown API Deployment Strategy

This document outlines the deployment strategy for the MarkItDown API service as a microservice within the Pretuned AI ecosystem.

## Overview

The MarkItDown API is deployed as a separate microservice but coordinated with the main backend API deployment. This approach provides several benefits:

1. **Independent Scaling**: The document conversion service can be scaled independently based on its specific resource needs.
2. **Isolation**: Issues with document processing won't affect the main application.
3. **Technology Independence**: The Python-based MarkItDown service can evolve separately from the TypeScript backend.

## Repository Structure

```
markitdown-api/                          # Separate GitHub repository
├── api.py                               # FastAPI application
├── requirements.txt                     # Python dependencies
├── Dockerfile                           # Container image definition
├── k8s/                                 # Kubernetes manifests
│   ├── deployment.yaml                  # Deployment configuration
│   └── service.yaml                     # Service configuration
└── .github/
    └── workflows/
        └── deploy.yml                   # Deployment workflow

pretuned__backend-api/                   # Main backend repository
├── src/
│   └── api/
│       └── v1/
│           └── modules/
│               ├── document-converter/  # Integration with MarkItDown
│               └── agents/              # Intent handling for documents
└── .github/
    └── workflows/
        └── deploy-integration.yml       # Coordinated deployment workflow
```

## Deployment Process

### 1. GitHub Actions Workflow

The deployment process is automated using GitHub Actions workflows:

- **MarkItDown API Workflow** (`.github/workflows/deploy.yml`):
  - Triggered on pushes to main/staging branches or manually
  - Builds and pushes Docker image
  - Deploys to Kubernetes with environment-specific configuration

- **Backend API Integration Workflow** (`.github/workflows/deploy-integration.yml`):
  - Triggers the MarkItDown deployment first
  - Deploys the backend API with proper configuration to connect to MarkItDown

### 2. Kubernetes Resources

The MarkItDown API is deployed with the following Kubernetes resources:

- **Deployment**: Manages the MarkItDown API pods
- **Service**: Exposes the API within the cluster
- **ConfigMap**: Stores configuration values
- **Ingress** (optional): Exposes the API externally if needed

### 3. Integration with Backend API

The backend API connects to the MarkItDown service using:

```
MARKITDOWN_URL=http://markitdown-service.default.svc.cluster.local
```

This environment variable is configured in the backend API's deployment process via ConfigMap.

## Environment-Specific Configuration

### Staging Environment

- **Replicas**: 2
- **Domain**: staging-markitdown-api.pretuned.ai
- **Resources**:
  - Memory: 256Mi (request), 512Mi (limit)
  - CPU: 100m (request), 500m (limit)

### Production Environment

- **Replicas**: 3
- **Domain**: markitdown-api.pretuned.ai
- **Resources**:
  - Memory: 256Mi (request), 512Mi (limit)
  - CPU: 100m (request), 500m (limit)

## Deployment Verification

After deployment, verify the service is working correctly by:

1. Checking pod status: `kubectl get pods -n default -l app=markitdown`
2. Verifying service availability: `kubectl exec -it <any-backend-pod> -- curl markitdown-service/health`
3. Testing document conversion through the backend API

## Rollback Strategy

If issues are detected after deployment:

1. Identify the issue through logs: `kubectl logs -l app=markitdown`
2. Roll back to previous version: `kubectl rollout undo deployment/markitdown`
3. If necessary, update the backend API to use a fallback mechanism

## Security Considerations

- The MarkItDown API is not exposed externally, only accessible within the cluster
- Document processing is isolated from the main application
- Input validation is performed on all document conversion requests
- Resource limits prevent denial-of-service attacks

## Monitoring and Logging

- **Health Checks**: The `/health` endpoint provides service health information
- **Kubernetes Probes**: Readiness and liveness probes ensure service availability
- **Logs**: All conversion operations are logged for debugging and auditing

## Future Improvements

1. Add horizontal pod autoscaling based on CPU/memory usage
2. Implement distributed tracing for request flows
3. Add metrics collection for conversion performance
4. Set up alerting for service degradation
