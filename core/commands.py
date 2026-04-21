from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from enum import Enum

class CommandContext(Enum):
    """Where a command is valid."""
    CLIP = "clip"           # right-click on a clip
    TRACK = "track"         # right-click on a track header
    TIMELINE = "timeline"   # right-click on empty timeline
    MEDIA_BIN = "media_bin" # right-click in media bin
    GLOBAL = "global"       # always available (menu bar)

@dataclass
class Command:
    """
    A single registered action.
    Add a new feature = add a new Command. Nothing else changes.
    """
    id: str                          # unique key e.g. 'scale_to_frame'
    label: str                       # shown in menu e.g. 'Scale to Frame'
    handler: Callable                # function to call
    context: CommandContext = CommandContext.CLIP
    shortcut: Optional[str] = None   # e.g. 'Ctrl+R'
    enabled_check: Optional[Callable] = None  # returns bool
    separator_before: bool = False   # draw a line above this item
    group: str = ''                  # visual grouping

class CommandRegistry:
    """
    Central registry for all actions in the app.
    UI reads from this — menus, toolbars, shortcuts all 
    built from the same source of truth.
    """
    def __init__(self):
        self._commands: Dict[str, Command] = {}

    def register(self, command: Command):
        self._commands[command.id] = command

    def get(self, command_id: str) -> Optional[Command]:
        return self._commands.get(command_id)

    def get_for_context(self, 
                        context: CommandContext) -> List[Command]:
        """Returns all commands valid for a given context,
        in registration order."""
        return [
            cmd for cmd in self._commands.values()
            if cmd.context == context
        ]

    def execute(self, command_id: str, **kwargs) -> Any:
        cmd = self.get(command_id)
        if cmd:
            return cmd.handler(**kwargs)

# Global singleton — imported everywhere
registry = CommandRegistry()

def register_command(id: str,
                     label: str,
                     handler: Callable,
                     context: CommandContext = CommandContext.CLIP,
                     shortcut: str = None,
                     separator_before: bool = False,
                     group: str = '') -> Command:
    """Convenience decorator/function for registering commands."""
    cmd = Command(
        id=id,
        label=label,
        handler=handler,
        context=context,
        shortcut=shortcut,
        separator_before=separator_before,
        group=group
    )
    registry.register(cmd)
    return cmd