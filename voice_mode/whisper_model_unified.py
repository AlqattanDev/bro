"""Unified whisper model command - getter/setter pattern."""

import click
import asyncio
import json
from pathlib import Path


def model_name_completion(ctx, args, incomplete):
    """Provide shell completion for model names."""
    from voice_mode.tools.whisper.models import WHISPER_MODEL_REGISTRY
    return [name for name in WHISPER_MODEL_REGISTRY.keys() if name.startswith(incomplete)]


@click.command("model",
    epilog="""
Examples:
  voicemode whisper model              # Show current model
  voicemode whisper model --all        # List all models
  voicemode whisper model large-v2     # Switch to (and install) large-v2
  voicemode whisper model tiny --no-install  # Switch to tiny (must be installed)
""")
@click.help_option('-h', '--help')
@click.argument('model_name', required=False, shell_complete=model_name_completion)
@click.option('--all', '-a', is_flag=True, help='List all available models')
@click.option('--no-install', is_flag=True, help="Don't auto-install missing models")
@click.option('--no-activate', is_flag=True, help="Don't auto-activate after installing")
@click.option('--no-restart', is_flag=True, help="Don't auto-restart whisper service after changing model")
def whisper_model_unified(model_name, all, no_install, no_activate, no_restart):
    """Show, set, or list Whisper models.

    Without arguments: Shows the current active model
    With MODEL_NAME: Sets the active model (auto-installs if needed)
    With --all/-a: Lists all available models with status
    """
    from voice_mode.tools.whisper.models import (
        WHISPER_MODEL_REGISTRY,
        get_model_directory,
        get_active_model,
        is_whisper_model_installed,
        get_installed_whisper_models,
        format_size,
        has_whisper_coreml_model,
        set_active_model
    )
    import subprocess

    # List all models mode
    if all:
        model_dir = get_model_directory()
        current_model = get_active_model()
        installed_models = get_installed_whisper_models()

        # Calculate totals in MB (format_size expects MB)
        total_installed_size = sum(
            WHISPER_MODEL_REGISTRY[name]["size_mb"]
            for name in installed_models
        )

        total_available_size = sum(
            info["size_mb"]
            for info in WHISPER_MODEL_REGISTRY.values()
        )

        click.echo("\nWhisper Models:\n")

        # Display each model
        for name, info in WHISPER_MODEL_REGISTRY.items():
            is_installed = is_whisper_model_installed(name)
            has_coreml = has_whisper_coreml_model(name)

            # Status indicator
            if is_installed and has_coreml:
                status = "[✓ Installed+ML]"
            elif is_installed:
                status = "[✓ Installed]"
            else:
                status = "[ Download ]"

            # Active model indicator
            prefix = "→ " if name == current_model else "  "

            # Format size
            size_mb = info["size_mb"]
            if size_mb >= 1000:
                size_str = f"{size_mb / 1000:.1f} GB"
            else:
                size_str = f"{size_mb} MB"

            # Format description
            desc = info["description"]
            if name == current_model:
                desc += " (active)"

            # Print model line
            click.echo(
                f"{prefix}{name:15} {status:16} {size_str:7} "
                f"{info['languages']:20} {desc}"
            )

        # Show summary
        click.echo(f"\nModels directory: {model_dir}")
        if total_installed_size > 0:
            click.echo(
                f"Total size: {format_size(total_installed_size)} installed / "
                f"{format_size(total_available_size)} available"
            )

        click.echo("\nTo use a model: voicemode whisper model <model-name>")
        return

    # Set model mode
    if model_name:
        # Validate model name
        if model_name not in WHISPER_MODEL_REGISTRY:
            click.echo(f"Error: '{model_name}' is not a valid model.", err=True)
            click.echo("\nAvailable models:", err=True)
            for name in WHISPER_MODEL_REGISTRY.keys():
                click.echo(f"  - {name}", err=True)
            raise click.Abort()

        # Check if model is installed
        if not is_whisper_model_installed(model_name):
            if no_install:
                click.echo(f"Error: Model '{model_name}' is not installed.", err=True)
                click.echo(f"Install it with: voicemode whisper model {model_name}", err=True)
                click.echo(f"(or remove --no-install flag to auto-install)", err=True)
                raise click.Abort()
            else:
                # Auto-install the model
                click.echo(f"Model '{model_name}' not installed. Installing...")

                # Import and run the installer
                import voice_mode.tools.whisper.model_install as install_module
                tool = install_module.whisper_model_install
                install_func = tool.fn if hasattr(tool, 'fn') else tool

                # Run installation
                result = asyncio.run(install_func(
                    model=model_name,
                    force_download=False,
                    skip_core_ml=False
                ))

                try:
                    data = json.loads(result)
                    if not data.get('success'):
                        click.echo(f"❌ Failed to install model: {data.get('error', 'Unknown error')}", err=True)
                        raise click.Abort()
                    click.echo(f"✅ Model '{model_name}' installed successfully!")
                except json.JSONDecodeError:
                    click.echo(f"❌ Failed to parse installation result", err=True)
                    raise click.Abort()

        # Now activate the model (unless --no-activate was specified)
        if no_activate:
            click.echo(f"Model '{model_name}' is available but not activated (--no-activate flag)")
        else:
            # Get previous model
            previous_model = get_active_model()

            # Update the configuration
            set_active_model(model_name)

            click.echo(f"✓ Active model set to: {model_name}")
            if previous_model != model_name:
                click.echo(f"  (was: {previous_model})")

            # Check if whisper service is running and restart if needed
            if not no_restart:
                try:
                    result = subprocess.run(['pgrep', '-f', 'whisper-server'], capture_output=True)
                    if result.returncode == 0:
                        # Service is running, restart it
                        click.echo(f"\nRestarting whisper service...")

                        # Import and use the restart function
                        from voice_mode.tools.service import restart_service
                        restart_result = asyncio.run(restart_service("whisper"))

                        if "✅" in restart_result or "started" in restart_result.lower():
                            click.echo(f"✓ Whisper service restarted with {model_name} model")
                        else:
                            click.echo(f"⚠️  Could not restart whisper service automatically")
                            click.echo(f"  Please run: {click.style('voicemode whisper restart', fg='yellow', bold=True)}")
                except Exception as e:
                    click.echo(f"⚠️  Could not restart whisper service: {e}")
                    click.echo(f"  Please run: {click.style('voicemode whisper restart', fg='yellow', bold=True)}")
            else:
                # no_restart flag was used
                try:
                    result = subprocess.run(['pgrep', '-f', 'whisper-server'], capture_output=True)
                    if result.returncode == 0:
                        click.echo(f"\n⚠️  Please restart the whisper service for changes to take effect:")
                        click.echo(f"  {click.style('voicemode whisper restart', fg='yellow', bold=True)}")
                        click.echo(f"  (auto-restart skipped due to --no-restart flag)")
                except:
                    pass

        return

    # Default: Show current model (getter mode)
    current = get_active_model()
    installed = is_whisper_model_installed(current)
    status = click.style("[✓ Installed]", fg="green") if installed else click.style("[Not installed]", fg="red")

    # Get model info
    model_info = WHISPER_MODEL_REGISTRY.get(current, {})

    click.echo(f"\nActive Whisper model: {click.style(current, fg='yellow', bold=True)} {status}")
    if model_info:
        size_mb = model_info.get('size_mb', 0)
        if size_mb >= 1000:
            size_str = f"{size_mb / 1000:.1f} GB"
        else:
            size_str = f"{size_mb} MB"

        click.echo(f"  Size: {size_str}")
        click.echo(f"  Languages: {model_info.get('languages', 'Unknown')}")
        click.echo(f"  Description: {model_info.get('description', 'Unknown')}")

    # Check service status
    try:
        result = subprocess.run(['pgrep', '-f', 'whisper-server'], capture_output=True)
        if result.returncode == 0:
            click.echo(f"\nWhisper service status: {click.style('Running', fg='green')}")
    except:
        pass

    click.echo(f"\nTo change: voicemode whisper model <model-name>")
    click.echo(f"To list all: voicemode whisper model --all")