from opendevin.core.config import config
from opendevin.core.utils import json
from opendevin.events.action import (
    Action,
)
from opendevin.events.observation import (
    CmdOutputObservation,
)
from opendevin.events.serialization.action import action_from_dict

ACTION_PROMPT = """
You're a thoughtful robot. Your main task is this:
%(task)s

Don't expand the scope of your task--just complete it as written.

This is your internal monologue, in JSON format:

%(monologue)s

Your most recent thought is at the bottom of that monologue. Continue your train of thought.
What is your next single thought or action? Your response must be in JSON format.
It must be a single object, and it must contain two fields:
* `action`, which is one of the actions below
* `args`, which is a map of key-value pairs, specifying the arguments for that action

Here are the possible actions:
* `read` - reads the content of a file. Arguments:
  * `path` - the path of the file to read
* `write` - writes the content to a file. Arguments:
  * `path` - the path of the file to write
  * `content` - the content to write to the file
* `run` - runs a command. Arguments:
  * `command` - the command to run
  * `background` - if true, run the command in the background, so that other commands can be run concurrently. Useful for e.g. starting a server. You won't be able to see the logs. You don't need to end the command with `&`, just set this to true.
* `kill` - kills a background command
  * `command_id` - the ID of the background command to kill
* `browse` - opens a web page. Arguments:
  * `url` - the URL to open
* `push` - Push a branch from the current repo to github:
  * `owner` - the owner of the repo to push to
  * `repo` - the name of the repo to push to
  * `branch` - the name of the branch to push
* `recall` - recalls a past memory. Arguments:
  * `query` - the query to search for
* `message` - make a plan, set a goal, record your thoughts, or ask for more input from the user. Arguments:
  * `content` - the message to record
  * `wait_for_response` - set to `true` to wait for the user to respond before proceeding
* `finish` - if you're absolutely certain that you've completed your task and have tested your work, use the finish action to stop working.

%(background_commands)s

You MUST take time to think in between read, write, run, kill, browse, push, and recall actions--do this with the `message` action.
You should never act twice in a row without thinking. But if your last several
actions are all `message` actions, you should consider taking a different action.

Notes:
* you are logged in as %(user)s, but sudo will always work without a password.
* all non-background commands will be forcibly stopped if they remain running for over %(timeout)s seconds.
* your environment is Debian Linux. You can install software with `sudo apt-get`, but remember to use -y.
* don't run interactive commands, or commands that don't return (e.g. `node server.js`). You may run commands in the background (e.g. `node server.js &`)
* don't run interactive text editors (e.g. `nano` or 'vim'), instead use the 'write' or 'read' action.
* don't run gui applications (e.g. software IDEs (like vs code or codium), web browsers (like firefox or chromium), or other complex software packages). Use non-interactive cli applications, or special actions instead.
* whenever an action fails, always send a `message` about why it may have happened before acting again.

What is your next single thought or action? Again, you must reply with JSON, and only with JSON. You must respond with exactly one 'action' object.

%(hint)s
"""

MONOLOGUE_SUMMARY_PROMPT = """
Below is the internal monologue of an automated LLM agent. Each
thought is an item in a JSON array. The thoughts may be memories,
actions taken by the agent, or outputs from those actions.

The monologue has two parts: the default memories, which you must not change,
they are provided to you only for context, and the recent monologue.

Please return a new, much smaller JSON array that summarizes the recent monologue.
When summarizing, you should condense the events that appear earlier
in the recent monologue list more aggressively, while preserving more details
for the events that appear later in the list.

You can summarize individual thoughts, and you can condense related thoughts
together with a description of their content.

%(monologue)s

Make the summaries as pithy and informative as possible, especially for the earlier events
in the old monologue.

Be specific about what happened and what was learned. The summary
will be used as keywords for searching for the original memory.
Be sure to preserve any key words or important information.

Your response must be in JSON format. It must be an object with the key `new_monologue`,
which must be a smaller JSON array containing the summarized monologue.
Each entry in the new monologue must have an `action` key, and an `args` key.
You can add a summarized entry with `action` set to "summarize" and a concise summary
in `args.summary`. You can also use the source recent event if relevant, with its original `action` and `args`.

Remember you must only summarize the old monologue, not the default memories.
"""

INITIAL_THOUGHTS = [
    'I exist!',
    'Hmm...looks like I can type in a command line prompt',
    'Looks like I have a web browser too!',
    "Here's what I want to do: $TASK",
    'How am I going to get there though?',
    'It seems like I have some kind of short term memory.',
    'Each of my thoughts seems to be stored in a JSON array.',
    'It seems whatever I say next will be added as an object to the list.',
    'But no one has perfect short-term memory. My list of thoughts will be summarized and condensed over time, losing information in the process.',
    'Fortunately I have long term memory!',
    'I can just perform a recall action, followed by the thing I want to remember. And then related thoughts just spill out!',
    "Sometimes they're random thoughts that don't really have to do with what I wanted to remember. But usually they're exactly what I need!",
    "Let's try it out!",
    'RECALL what it is I want to do',
    "Here's what I want to do: $TASK",
    'How am I going to get there though?',
    "Neat! And it looks like it's easy for me to use the command line too! I just have to perform a run action and include the command I want to run in the command argument. The command output just jumps into my head!",
    'RUN echo "hello world"',
    'hello world',
    'Cool! I bet I can write files too using the write action.',
    'WRITE echo "console.log(\'hello world\')" > test.js',
    '',
    "I just created test.js. I'll try and run it now.",
    'RUN node test.js',
    'hello world',
    'It works!',
    "I'm going to try reading it now using the read action.",
    'READ test.js',
    "console.log('hello world')",
    'Nice! I can read files too!',
    'And if I want to use the browser, I just need to use the browse action and include the url I want to visit in the url argument',
    "Let's try that...",
    'BROWSE google.com',
    '<form><input type="text"></input><button type="submit"></button></form>',
    'I can browse the web too!',
    'And once I have completed my task, I can use the finish action to stop working.',
    "But I should only use the finish action when I'm absolutely certain that I've completed my task and have tested my work.",
    'Very cool. Now to accomplish my task.',
    "I'll need a strategy. And as I make progress, I'll need to keep refining that strategy. I'll need to set goals, and break them into sub-goals.",
    'In between actions, I must always take some time to think, strategize, and set new goals. I should never take two actions in a row.',
    "OK so my task is to $TASK. I haven't made any progress yet. Where should I start?",
    'It seems like there might be an existing project here. I should probably start by running `pwd` and `ls` to orient myself.',
]


def get_summarize_monologue_prompt(recent_events: list[dict]):
    """
    Gets the prompt for summarizing the monologue

    Returns:
    - str: A formatted string with the current monologue within the prompt
    """
    return MONOLOGUE_SUMMARY_PROMPT % {
        'monologue': json.dumps({'old_monologue': recent_events}, indent=2),
    }


def get_action_prompt(
    task: str,
    default_events: list[dict],
    recent_events: list[dict],
    background_commands_obs: list[CmdOutputObservation] | None = None,
):
    """
    Gets the action prompt formatted with appropriate values.

    Parameters:
    - task: The current task the agent is trying to accomplish
    - thoughts: The agent's current thoughts
    - background_commands_obs: list of all observed background commands running

    Returns:
    - str: Formatted prompt string with hint, task, monologue, and background commands included
    """

    if background_commands_obs is None:
        background_commands_obs = []

    hint = ''
    if recent_events is not None and len(recent_events) > 0:
        latest_event = recent_events[-1]
        if 'action' in latest_event:
            if (
                latest_event['action'] == 'message'
                and 'source' in latest_event
                and latest_event['source'] == 'agent'
            ):
                hint = (
                    "You've been thinking a lot lately. Maybe it's time to take action?"
                )
            elif latest_event['action'] == 'error':
                hint = 'Looks like that last command failed. Maybe you need to fix it, or try something else.'
    else:
        hint = "You're just getting started! What should you do first?"
    bg_commands_message = ''
    if len(background_commands_obs) > 0:
        bg_commands_message = 'The following commands are running in the background:'
        for command_obs in background_commands_obs:
            bg_commands_message += (
                f'\n`{command_obs.command_id}`: {command_obs.command}'
            )
        bg_commands_message += '\nYou can end any process by sending a `kill` action with the numerical `command_id` above.'

    user = 'opendevin' if config.run_as_devin else 'root'

    monologue = default_events + recent_events

    return ACTION_PROMPT % {
        'task': task,
        'monologue': json.dumps(monologue, indent=2),
        'background_commands': bg_commands_message,
        'hint': hint,
        'user': user,
        'timeout': config.sandbox_timeout,
        # unused 'workspace_mount_path_in_sandbox': config.workspace_mount_path_in_sandbox,
    }


def get_action_prompt_template(
    task: str,
    default_events: list[dict],
    background_commands_obs: list[CmdOutputObservation],
) -> str:
    """
    Gets the action prompt template with default_events pre-filled and a placeholder for recent_events and hint.

    Parameters:
    - task: The current task the agent is trying to accomplish
    - default_events: The default events to include in the prompt
    - background_commands_obs: list of all observed background commands running

    Returns:
    - str: Formatted prompt template string with default_events pre-filled and placeholders for recent_events and hint
    """
    bg_commands_message = format_background_commands(background_commands_obs)
    user = 'opendevin' if config.run_as_devin else 'root'

    return ACTION_PROMPT % {
        'task': task,
        'monologue': json.dumps(default_events, indent=2) + '%(recent_events)s',
        'background_commands': bg_commands_message,
        'hint': '%(hint)s',
        'user': user,
        'timeout': config.sandbox_timeout,
    }


def get_action_prompt_for_summarization(
    prompt_template: str,
    recent_events: list[dict],
) -> str:
    """
    Gets the action prompt formatted with recent_events and a generated hint.

    Parameters:
    - prompt_template: The prompt template with placeholders for recent_events and hint
    - recent_events: The recent events to include in the prompt

    Returns:
    - str: Formatted prompt string with recent_events and a generated hint included
    """
    hint = ''
    if recent_events is not None and len(recent_events) > 0:
        latest_thought = recent_events[-1]
        if 'action' in latest_thought:
            if latest_thought['action'] == 'message':
                if latest_thought['args']['content'].startswith('OK so my task is'):
                    hint = "You're just getting started! What should you do first?"
                else:
                    hint = "You've been thinking a lot lately. Maybe it's time to take action?"
            elif latest_thought['action'] == 'error':
                hint = 'Looks like that last command failed. Maybe you need to fix it, or try something else.'

    return prompt_template % {
        'recent_events': json.dumps(recent_events, indent=2),
        'hint': hint,
    }


def format_background_commands(
    background_commands_obs: list[CmdOutputObservation] | None,
) -> str:
    """
    Formats the background commands for sending in the prompt

    Parameters:
    - background_commands_obs: list of all background commands running

    Returns:
    - Formatted string with all background commands
    """
    if background_commands_obs is None or len(background_commands_obs) == 0:
        return ''

    bg_commands_message = 'The following commands are running in the background:'
    for obs in background_commands_obs:
        bg_commands_message += f'\n`{obs.command_id}`: {obs.command}'
    bg_commands_message += '\nYou can end any process by sending a `kill` action with the numerical `command_id` above.'

    return bg_commands_message


def parse_action_response(orig_response: str) -> Action:
    """
    Parses a string to find an action within it

    Parameters:
    - orig_response: The string to be parsed

    Returns:
    - The action that was found in the response string
    """
    # attempt to load the JSON dict from the response
    action_dict = json.loads(orig_response)

    if 'content' in action_dict:
        # The LLM gets confused here. Might as well be robust
        action_dict['contents'] = action_dict.pop('content')

    return action_from_dict(action_dict)


def get_summarize_prompt(default_events: list[dict], recent_events: list[dict]):
    """
    Gets the prompt for summarizing the monologue

    Returns:
    - A formatted string with the current monologue within the prompt
    """
    return MONOLOGUE_SUMMARY_PROMPT % {
        'monologue': json.dumps(
            {'default_memories': default_events, 'old_monologue': recent_events},
            indent=2,
        ),
    }


def parse_summary_response(response: str) -> list[dict]:
    """
    Parses a summary of the monologue

    Parameters:
    - response: The response string to be parsed

    Returns:
    - The list of summaries output by the model
    """
    parsed = json.loads(response)
    return parsed['new_monologue']


def generate_action_prompt_with_defaults(**kwargs):
    # prepare the placeholders dict
    placeholders = {
        'task': '%(task)s',
        'background_commands': '%(background_commands)s',
        'hint': '%(hint)s',
        'user': '%(user)s',
        'timeout': '%(timeout)s',
        'workspace_mount_path_in_sandbox': '%(workspace_mount_path_in_sandbox)s',
    }

    # update the placeholders with the provided values
    monologue = []
    formatted_kwargs = {}
    for key, value in kwargs.items():
        if key in ['default_events', 'recent_events'] and value is not None:
            monologue.extend(value)
        elif key == 'background_commands':
            formatted_kwargs[key] = format_background_commands(value)
        else:
            formatted_kwargs[key] = value
    formatted_kwargs['monologue'] = json.dumps(monologue, indent=2)

    placeholders.update(formatted_kwargs)

    # format the template with what we have
    # FIXME the split of default and recent events
    return ACTION_PROMPT % placeholders
