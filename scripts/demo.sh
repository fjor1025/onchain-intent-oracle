#!/bin/bash
set -e

echo "OnChainIntentOracle Demo"
echo "========================="

# Check environment
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Warning: ANTHROPIC_API_KEY not set. LLM features will be disabled."
fi

if [ -z "$ALCHEMY_RPC" ] && [ -z "$RPC_URLS" ]; then
    echo "Warning: No RPC URL configured. Set ALCHEMY_RPC or RPC_URLS."
fi

# Demo: Analyze USDC
echo ""
echo "Demo 1: Analyzing USDC (0xA0b86991...)"
echo "This will fetch transaction history and infer behavior."
echo ""

oio analyze     0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48     --chain ethereum     --block-range 18000000:18001000     --output ./demo-output/usdc     --depth quick     --cache-ns demo-usdc

echo ""
echo "Demo 2: Generate report from analysis"
oio report demo-usdc --format markdown

echo ""
echo "Demo complete! Check ./demo-output/ for results."
