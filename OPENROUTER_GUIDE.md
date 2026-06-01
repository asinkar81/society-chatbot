# Using Claude Vision with OpenRouter.ai

This guide explains how to use Claude Vision and other Anthropic models through OpenRouter.ai as an alternative to the direct Anthropic API.

## What is OpenRouter?

OpenRouter is a unified API gateway that provides access to multiple Large Language Models (LLMs), including:
- Anthropic's Claude models (including Claude Vision)
- Other popular models like GPT-4, Llama, etc.

## Why Use OpenRouter?

1. **Cost Management**: OpenRouter often offers competitive pricing and usage monitoring
2. **Unified Interface**: Manage multiple models through a single API
3. **No Model Availability Issues**: Access models even if they're not available in your region
4. **Extended Features**: Better rate limiting, logging, and analytics capabilities
5. **Easy Fallback**: Quickly switch between models if needed

## Setup Instructions

### 1. Get an OpenRouter API Key

1. Visit [OpenRouter.ai](https://openrouter.ai/)
2. Sign up for a free account
3. Navigate to your Dashboard and locate your API key
4. Copy your API key (you can also find models and pricing here)

### 2. Update Your Environment Configuration

Edit your `.env` file and set:

```bash
# Choose your LLM provider
LLM_PROVIDER=openrouter

# Add your OpenRouter API key
OPENROUTER_API_KEY=sk-or-YOUR_OPENROUTER_KEY_HERE

# Optional: Add your site info for OpenRouter analytics
OPENROUTER_SITE_URL=http://localhost:8501
OPENROUTER_SITE_NAME=Society Chatbot
```

**Note**: You can comment out or remove `ANTHROPIC_API_KEY` when using OpenRouter.

### 3. Verify Configuration

The application will automatically:
- Use OpenRouter's API endpoints
- Configure Claude Vision for OCR/payment screenshot processing
- Use Claude Haiku for general agent tasks
- Send your site information to OpenRouter for analytics

## How It Works

### For Text-Based Agents
The system uses `claude-3-5-haiku-20241022` through OpenRouter for:
- Receipt generation
- Ledger management
- Invoice processing
- Admin operations

### For Vision Tasks (OCR)
The system uses `claude-3-5-sonnet-20241022` through OpenRouter for:
- Payment screenshot analysis
- Text extraction from images
- Document recognition

## Comparing Costs

When you access OpenRouter's dashboard, you can see:
- Token usage for each model
- Cost per request
- Total spending

Claude through OpenRouter may be cheaper than direct API access depending on your usage patterns.

## Testing Your Setup

Run this command to verify the configuration:

```bash
# Activate virtual environment
source venv/bin/activate

# Start the application
streamlit run main.py
```

If everything is configured correctly:
- The chatbot will start normally
- Vision features (payment screenshot analysis) will work via OpenRouter
- You'll see requests logged in your OpenRouter dashboard

## Switching Between Providers

To switch back to direct Anthropic API:

```bash
# In your .env file, change:
LLM_PROVIDER=anthropic

# And ensure ANTHROPIC_API_KEY is set
ANTHROPIC_API_KEY=your-direct-anthropic-key
```

## Troubleshooting

### Error: "OPENROUTER_API_KEY environment variable not set"
- Make sure `OPENROUTER_API_KEY` is in your `.env` file
- Make sure you've set `LLM_PROVIDER=openrouter`
- Run `source venv/bin/activate` to reload environment variables

### Vision features not working
- Verify you have credits on your OpenRouter account
- Check that the API key has permissions for vision models
- Review your OpenRouter dashboard for any errors

### Rate limiting
- OpenRouter may rate limit high-frequency requests
- Monitor your usage in the OpenRouter dashboard
- Consider upgrading your account for higher limits

## Supported Models

The current implementation uses:
- **Main Model**: `claude-3-5-haiku-20241022` (for agents)
- **Vision Model**: `claude-3-5-sonnet-20241022` (for OCR/payment processing)

You can modify these in `config.py`:

```python
LLM_MODEL_MAIN = "claude-3-5-haiku-20241022"
LLM_MODEL_VISION = "claude-3-5-sonnet-20241022"
```

## Additional Resources

- [OpenRouter Documentation](https://openrouter.ai/docs)
- [Anthropic Claude Models](https://console.anthropic.com/docs/models)
- [OpenRouter Pricing](https://openrouter.ai/pricing)

## Support

For issues with:
- **OpenRouter**: Visit [OpenRouter Support](https://openrouter.ai/)
- **This Application**: Check the main README.md or project documentation
- **Anthropic APIs**: Visit [Anthropic Docs](https://docs.anthropic.com/)
