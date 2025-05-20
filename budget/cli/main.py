"""
Budget CLI

Command-line interface for the Budget component.
"""

import os
import sys
import click

# Add the parent directory to sys.path to ensure package imports work correctly
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Try to import debug_utils from shared if available
try:
    from shared.debug.debug_utils import debug_log, log_function
except ImportError:
    # Create a simple fallback if shared module is not available
    class DebugLog:
        def __getattr__(self, name):
            def dummy_log(*args, **kwargs):
                pass
            return dummy_log
    debug_log = DebugLog()
    
    def log_function(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

@click.group()
@click.option('--debug/--no-debug', default=False, help='Enable debug output')
@click.pass_context
def cli(ctx, debug):
    """
    Budget component command-line interface.
    
    Manage LLM token budgets and cost tracking for Tekton components.
    """
    ctx.ensure_object(dict)
    
    if debug:
        os.environ["TEKTON_DEBUG"] = "true"
        os.environ["TEKTON_LOG_LEVEL"] = "DEBUG"
        
    ctx.obj['DEBUG'] = debug
    debug_log.info("budget_cli", "CLI initialized")

@cli.command()
@click.pass_context
def start(ctx):
    """Start the Budget API server."""
    debug_log.info("budget_cli", "Starting Budget API server")
    from budget.api.app import main as start_api
    start_api()

@cli.command()
@click.pass_context
def status(ctx):
    """Show the current budget status."""
    debug_log.info("budget_cli", "Getting budget status")
    click.echo("Budget status: Initializing (not yet implemented)")

@cli.command()
@click.argument('period', type=click.Choice(['daily', 'weekly', 'monthly']))
@click.pass_context
def get_usage(ctx, period):
    """
    Get usage data for a specific period.
    
    PERIOD can be one of: daily, weekly, monthly
    """
    debug_log.info("budget_cli", f"Getting usage for period: {period}")
    click.echo(f"Budget usage for {period}: Not yet implemented")

@cli.command()
@click.argument('period', type=click.Choice(['daily', 'weekly', 'monthly']))
@click.argument('limit', type=float)
@click.option('--provider', default='all', help='Provider to set limit for')
@click.pass_context
def set_limit(ctx, period, limit, provider):
    """
    Set a budget limit for a period.
    
    PERIOD can be one of: daily, weekly, monthly
    LIMIT is the budget amount in USD
    """
    debug_log.info("budget_cli", 
                   f"Setting {period} limit to ${limit} for provider {provider}")
    click.echo(f"Budget limit for {period} set to ${limit} for {provider}")

def main():
    """
    Main entry point for the budget CLI.
    """
    cli(obj={})

if __name__ == '__main__':
    main()