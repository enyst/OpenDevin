import agenthub.monologue_agent.utils.prompts as prompts
from agenthub.monologue_agent.utils.prompts import INITIAL_THOUGHTS
from opendevin.controller.agent import Agent
from opendevin.controller.state.state import State
from opendevin.core.config import config
from opendevin.core.exceptions import AgentNoInstructionError
from opendevin.core.schema import ActionType
from opendevin.events.action import (
    Action,
    AgentRecallAction,
    BrowseURLAction,
    CmdRunAction,
    FileReadAction,
    FileWriteAction,
    MessageAction,
    NullAction,
)
from opendevin.events.observation import (
    AgentRecallObservation,
    BrowserOutputObservation,
    CmdOutputObservation,
    FileReadObservation,
    NullObservation,
    Observation,
)
from opendevin.events.serialization.event import event_to_memory
from opendevin.llm.llm import LLM
from opendevin.memory.condenser import MemoryCondenser
from opendevin.runtime.tools import RuntimeTool

if config.agent.memory_enabled:
    from opendevin.memory.memory import LongTermMemory

MAX_OUTPUT_LENGTH = 5000


class MonologueAgent(Agent):
    VERSION = '1.0'
    """
    The Monologue Agent utilizes long and short term memory to complete tasks.
    Long term memory is stored as a LongTermMemory object and the model uses it to search for examples from the past.
    Short term memory is stored as a Monologue object and the model can condense it as necessary.
    """

    _initialized = False
    initial_thoughts: list[dict[str, str]]
    initial_thoughts_ids: list[int]
    longterm_memory: 'LongTermMemory | None'
    memory_condenser: MemoryCondenser | None
    runtime_tools: list[RuntimeTool] = [RuntimeTool.BROWSER]

    def __init__(self, llm: LLM):
        """
        Initializes the Monologue Agent with an llm.

        Parameters:
        - llm (LLM): The llm to be used by this agent
        """
        super().__init__(llm)
        self.longterm_memory = None
        self.memory_condenser = None

    def _initialize(self, task: str):
        """
        Utilizes the INITIAL_THOUGHTS list to give the agent a context for its capabilities
        and how to navigate the WORKSPACE_MOUNT_PATH_IN_SANDBOX in `config` (e.g., /workspace by default).
        Short circuited to return when already initialized.
        Will execute again when called after reset.

        Parameters:
        - task: The initial goal statement provided by the user

        Raises:
        - AgentNoInstructionError: If task is not provided
        """

        if self._initialized:
            return

        if task is None or task == '':
            raise AgentNoInstructionError()

        self.initial_thoughts = []
        self.initial_thoughts_ids = []
        if config.agent.memory_enabled:
            self.longterm_memory = LongTermMemory()
        else:
            self.longterm_memory = None

        # self.memory_condenser = MemoryCondenser(action_prompt=prompts.get_action_prompt)

        self._add_initial_thoughts(task)
        self._initialized = True

    def _add_initial_thoughts(self, task):
        previous_action = ''
        for thought in INITIAL_THOUGHTS:
            thought = thought.replace('$TASK', task)
            if previous_action != '':
                observation: Observation = NullObservation(content='')
                if previous_action in {ActionType.RUN, ActionType.PUSH}:
                    observation = CmdOutputObservation(
                        content=thought, command_id=0, command=''
                    )
                elif previous_action == ActionType.READ:
                    observation = FileReadObservation(content=thought, path='')
                elif previous_action == ActionType.RECALL:
                    observation = AgentRecallObservation(content=thought, memories=[])
                elif previous_action == ActionType.BROWSE:
                    observation = BrowserOutputObservation(
                        content=thought, url='', screenshot=''
                    )
                self.initial_thoughts.append(event_to_memory(observation))
                self.initial_thoughts_ids.append(observation.id)
                previous_action = ''
            else:
                action: Action = NullAction()
                if thought.startswith('RUN'):
                    command = thought.split('RUN ')[1]
                    action = CmdRunAction(command)
                    previous_action = ActionType.RUN
                elif thought.startswith('WRITE'):
                    parts = thought.split('WRITE ')[1].split(' > ')
                    path = parts[1]
                    content = parts[0]
                    action = FileWriteAction(path=path, content=content)
                elif thought.startswith('READ'):
                    path = thought.split('READ ')[1]
                    action = FileReadAction(path=path)
                    previous_action = ActionType.READ
                elif thought.startswith('RECALL'):
                    query = thought.split('RECALL ')[1]
                    action = AgentRecallAction(query=query)
                    previous_action = ActionType.RECALL
                elif thought.startswith('BROWSE'):
                    url = thought.split('BROWSE ')[1]
                    action = BrowseURLAction(url=url)
                    previous_action = ActionType.BROWSE
                else:
                    action = MessageAction(thought)
                self.initial_thoughts.append(event_to_memory(action))
                self.initial_thoughts_ids.append(action.id)
        if self.longterm_memory is not None:
            self.longterm_memory.add_events(
                events=self.initial_thoughts, ids=self.initial_thoughts_ids
            )

    def step(self, state: State) -> Action:
        """
        Modifies the current state by adding the most recent actions and observations, then prompts the model to think about it's next action to take using monologue, memory, and hint.

        Parameters:
        - state: The current state based on previous steps taken

        Returns:
        - The next action to take based on LLM response
        """

        goal = state.get_current_user_intent()
        self._initialize(goal)

        recent_events: list[dict[str, str]] = []

        # add the events from state.history
        for event in state.history.get_events():
            recent_events.append(event_to_memory(event))

        # add the last events to long term memory
        if self.longterm_memory is not None:
            last_action = state.history.get_last_action()
            last_observation = state.history.get_last_observation()

            if last_action:
                self.longterm_memory.add_event(
                    event_to_memory(last_action), id=last_action.id
                )
            if last_observation:
                self.longterm_memory.add_event(
                    event_to_memory(last_observation), id=last_observation.id
                )

        # the action prompt with initial thoughts and recent events
        prompt = prompts.get_action_prompt(
            goal,
            self.initial_thoughts,
            recent_events,
            state.background_commands_obs,  # FIXME is this part of recent_events?
        )

        messages: list[dict[str, str]] = [
            {'role': 'user', 'content': prompt},
        ]

        # format all as a single message, a monologue
        resp = self.llm.completion(messages=messages)

        # get the next action from the response
        action_resp = resp['choices'][0]['message']['content']

        # keep track of max_chars fallback option
        state.num_of_chars += len(prompt) + len(action_resp)

        action = prompts.parse_action_response(action_resp)
        self.latest_action = action
        return action

    def search_memory(self, query: str) -> list[str]:
        """
        Uses VectorIndexRetriever to find related memories within the long term memory.
        Uses search to produce top 10 results.

        Parameters:
        - The query that we want to find related memories for

        Returns:
        - A list of top 10 text results that matched the query
        """
        if self.longterm_memory is None:
            return []
        return self.longterm_memory.search(query)

    def reset(self) -> None:
        super().reset()

        # Reset the initial monologue and memory
        self._initialized = False
