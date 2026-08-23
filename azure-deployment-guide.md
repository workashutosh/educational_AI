# Azure Deployment Guide for Education AI

This guide will help you deploy your Django + React education AI application to Azure using GitHub Actions.

## Prerequisites

1. **Azure Account**: Sign up at [portal.azure.com](https://portal.azure.com)
2. **GitHub Repository**: Push your code to GitHub
3. **Azure CLI** (optional): For advanced configuration

## Deployment Options

### Option 1: Azure Web App (Recommended for beginners)

#### Step 1: Create Azure Resources

1. Go to [Azure Portal](https://portal.azure.com)
2. Click **"Create a resource"** → **"Web App"**
3. Fill in the details:
   - **App name**: `education-ai-app` (or your preferred name)
   - **Runtime**: Python 3.11
   - **Region**: Choose closest to your users
   - **Plan**: B1 Basic (or higher for production)

#### Step 2: Setup Database (Optional but recommended)

1. Create **"Azure Database for PostgreSQL"**
2. Note down the connection details:
   - Server name
   - Username
   - Password
   - Database name

#### Step 3: Configure GitHub Actions

1. In Azure Portal, go to your Web App
2. Navigate to **Deployment → Deployment Center**
3. Choose **GitHub** as source
4. Select your repository and branch
5. Download the **Publish Profile** (you'll need this)

#### Step 4: Setup GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and Variables → Actions** and add:

```
AZURE_WEBAPP_PUBLISH_PROFILE: [paste the downloaded publish profile]
SECRET_KEY: [generate a secure Django secret key]
DB_NAME: [your database name]
DB_USER: [your database user]
DB_PASSWORD: [your database password]
DB_HOST: [your database host]
```

### Option 2: Azure Container Apps (For advanced users)

#### Step 1: Create Azure Container Registry

```bash
# If you have Azure CLI installed
az group create --name education-ai-rg --location eastus
az acr create --resource-group education-ai-rg --name educationairegistry --sku Basic
```

#### Step 2: Setup GitHub Secrets for Container Deployment

Add these additional secrets:
```
REGISTRY_LOGIN_SERVER: educationairegistry.azurecr.io
REGISTRY_USERNAME: [from ACR access keys]
REGISTRY_PASSWORD: [from ACR access keys]
RESOURCE_GROUP: education-ai-rg
```

#### Step 3: Enable Container Deployment

In the GitHub Actions workflow file, change:
```yaml
containerized-deploy:
  if: true  # Change from false to true
```

## Environment Variables

Set these in Azure Portal → Configuration → Application Settings:

### Required
- `SECRET_KEY`: Django secret key
- `DEBUG`: false
- `ALLOWED_HOSTS`: your-app-name.azurewebsites.net

### Database (if using PostgreSQL)
- `DB_NAME`: Database name
- `DB_USER`: Database username  
- `DB_PASSWORD`: Database password
- `DB_HOST`: Database host
- `DB_PORT`: 5432

### Optional
- `USE_SQLITE`: true (for testing without external DB)
- `FORCE_HTTPS`: true (when SSL is configured)
- `AZURE_STORAGE_ACCOUNT_NAME`: For file uploads
- `AZURE_STORAGE_ACCOUNT_KEY`: Storage key
- `SENDGRID_API_KEY`: For email functionality

## Deployment Process

1. **Push to GitHub**: Commit and push your changes
2. **Automatic Deployment**: GitHub Actions will:
   - Build the React frontend
   - Setup Django backend
   - Deploy to Azure
   - Run migrations
   - Collect static files

## Monitoring

- **Logs**: Azure Portal → Monitoring → Log Stream
- **Metrics**: Monitor CPU, Memory, Response times
- **Alerts**: Set up alerts for errors or high resource usage

## Custom Domain (Optional)

1. Purchase a domain
2. In Azure Portal → Custom domains
3. Add your domain and configure DNS
4. Enable SSL certificate

## Scaling

- **Scale Up**: Increase CPU/RAM in Azure Portal → Scale up
- **Scale Out**: Add more instances in Scale out settings

## Troubleshooting

### Common Issues

1. **Build Failures**
   - Check GitHub Actions logs
   - Verify all secrets are set correctly

2. **Database Connection Errors**  
   - Verify database credentials
   - Check firewall settings in Azure

3. **Static Files Not Loading**
   - Ensure `collectstatic` runs in deployment
   - Check STATIC_ROOT configuration

### Useful Commands

```bash
# View logs (if Azure CLI is available)
az webapp log tail --name education-ai-app --resource-group your-rg

# Restart app
az webapp restart --name education-ai-app --resource-group your-rg
```

## Cost Optimization

- **Development**: Use B1 Basic plan
- **Production**: Consider P1V2 or higher
- **Database**: Use Basic tier for development
- **Storage**: Use locally-redundant storage (LRS)

## Security Checklist

- [ ] Set strong SECRET_KEY
- [ ] Enable HTTPS (FORCE_HTTPS=true)
- [ ] Configure proper ALLOWED_HOSTS
- [ ] Set up backup strategy
- [ ] Enable monitoring and alerts
- [ ] Review access permissions

## Next Steps

After successful deployment:
1. Test all functionality
2. Set up monitoring and backups
3. Configure custom domain
4. Set up CI/CD for other environments (staging, etc.)