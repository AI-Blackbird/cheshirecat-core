import time
import asyncio
import traceback
from asyncio import AbstractEventLoop

import tiktoken
from typing import Literal, get_args, List, Dict, Union, Any

from langchain.docstore.document import Document
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from langchain_community.llms import Cohere
from langchain_openai import ChatOpenAI, OpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from fastapi import WebSocket

from cat import utils
from cat.agents import AgentOutput
from cat.agents.main_agent import MainAgent
from cat.auth.permissions import AuthUserInfo
from cat.convo.messages import CatMessage, UserMessage, MessageWhy, Role, EmbedderModelInteraction
from cat.db import crud
from cat.env import get_env
from cat.factory.embedder import (
    EmbedderSettings,
    EmbedderDumbConfig,
    EmbedderOpenAIConfig,
    EmbedderCohereConfig,
    EmbedderGeminiChatConfig,
    get_embedder_from_name,
)
from cat.factory.llm import LLMDefaultConfig, get_llm_from_name
from cat.log import log
from cat.looking_glass.cheshire_cat import CheshireCat
from cat.looking_glass.callbacks import NewTokenHandler, ModelInteractionHandler
from cat.looking_glass.white_rabbit import WhiteRabbit
from cat.mad_hatter.mad_hatter import MadHatter
from cat.memory.working_memory import WorkingMemory
from cat.memory.long_term_memory import LongTermMemory
from cat.rabbit_hole import RabbitHole

MSG_TYPES = Literal["notification", "chat", "error", "chat_token"]


# The Stray cat goes around tools and hook, making troubles
class StrayCat:
    """User/session based object containing working memory and a few utility pointers"""

    def __init__(self, main_loop, user_data: AuthUserInfo = None, ws: WebSocket = None):
        self.__user = user_data
        self.working_memory = WorkingMemory()

        # Load language model and embedder
        self.llm = self.load_language_model()
        self.embedder = self.load_language_embedder()

        # Load memories (vector collections and working_memory)
        self.memory = self.load_memory()

        # After memory is loaded, we can get/create tools embeddings
        # every time the mad_hatter finishes syncing hooks, tools and forms, it will notify the Cat (so it can embed tools in vector memory)
        self.mad_hatter.on_finish_plugins_sync_callback = self.embed_procedures
        self.embed_procedures()  # first time launched manually

        # Main agent instance (for reasoning)
        self.main_agent = MainAgent()

        # attribute to store ws connection
        self.ws = ws

        self.__main_loop = main_loop

        self.__loop = asyncio.new_event_loop()
        self.__last_message_time = None

    def __repr__(self):
        return f"StrayCat(user_id={self.user_id})"

    def __send_ws_json(self, data: Any):
        # Run the coroutine in the main event loop in the main thread
        # and wait for the result
        asyncio.run_coroutine_threadsafe(self.ws.send_json(data), loop=self.__main_loop).result()

    def __build_why(self) -> MessageWhy:
        def build_report(memories):
            return [
                dict(d[0]) | {"score": float(d[1]), "id": d[3]}
                for d in memories
            ]

        # build data structure for output (response and why with memories)
        episodic_report = build_report(self.working_memory.episodic_memories)
        declarative_report = build_report(self.working_memory.declarative_memories)
        procedural_report = build_report(self.working_memory.procedural_memories)

        # why this response?
        why = MessageWhy(
            input=self.working_memory.user_message_json.text,
            intermediate_steps=[],
            memory={
                "episodic": episodic_report,
                "declarative": declarative_report,
                "procedural": procedural_report,
            },
            model_interactions=self.working_memory.model_interactions,
        )

        return why

    def load_language_model(self) -> BaseLanguageModel:
        """Large Language Model (LLM) selection.

        Returns
        -------
        llm : BaseLanguageModel
            Langchain `BaseLanguageModel` instance of the selected model.

        Notes
        -----
        Bootstrapping is the process of loading the plugins, the natural language objects (e.g. the LLM), the memories,
        the *Main Agent*, the *Rabbit Hole* and the *White Rabbit*.

        """

        selected_llm = crud.get_setting_by_name(name="llm_selected", user_id=self.user_id)

        if selected_llm is None:
            # return default LLM
            llm = LLMDefaultConfig.get_llm_from_config({})
        else:
            # get LLM factory class
            selected_llm_class = selected_llm["value"]["name"]
            FactoryClass = get_llm_from_name(selected_llm_class)

            # obtain configuration and instantiate LLM
            selected_llm_config = crud.get_setting_by_name(name=selected_llm_class, user_id=self.user_id)
            try:
                llm = FactoryClass.get_llm_from_config(selected_llm_config["value"])
            except Exception:
                import traceback

                traceback.print_exc()
                llm = LLMDefaultConfig.get_llm_from_config({})

        return llm

    def load_language_embedder(self) -> EmbedderSettings:
        """Hook into the  embedder selection.

        Allows to modify how the Cat selects the embedder at bootstrap time.

        Bootstrapping is the process of loading the plugins, the natural language objects (e.g. the LLM), the memories,
        the *Main Agent*, the *Rabbit Hole* and the *White Rabbit*.

        Returns
        -------
        embedder : Embeddings
            Selected embedder model.
        """
        # Embedding LLM

        selected_embedder = crud.get_setting_by_name(name="embedder_selected", user_id=self.user_id)

        if selected_embedder is not None:
            # get Embedder factory class
            selected_embedder_class = selected_embedder["value"]["name"]
            FactoryClass = get_embedder_from_name(selected_embedder_class)

            # obtain configuration and instantiate Embedder
            selected_embedder_config = crud.get_setting_by_name(name=selected_embedder_class, user_id=self.user_id)
            try:
                embedder = FactoryClass.get_embedder_from_config(selected_embedder_config["value"])
            except AttributeError:
                import traceback

                traceback.print_exc()
                embedder = EmbedderDumbConfig.get_embedder_from_config({})
            return embedder

        llm_type = type(self.llm)

        # OpenAI embedder
        if llm_type in [OpenAI, ChatOpenAI]:
            return EmbedderOpenAIConfig.get_embedder_from_config(
                {
                    "openai_api_key": self.llm.openai_api_key,
                }
            )

        # For Azure avoid automatic embedder selection

        # Cohere
        if llm_type in [Cohere]:
            return EmbedderCohereConfig.get_embedder_from_config(
                {
                    "cohere_api_key": self.llm.cohere_api_key,
                    "model": "embed-multilingual-v2.0",
                    # Now the best model for embeddings is embed-multilingual-v2.0
                }
            )

        if llm_type in [ChatGoogleGenerativeAI]:
            return EmbedderGeminiChatConfig.get_embedder_from_config(
                {
                    "model": "models/embedding-001",
                    "google_api_key": self.llm.google_api_key,
                }
            )

        # If no embedder matches vendor, and no external embedder is configured, we use the DumbEmbedder.
        #   `This embedder is not a model properly trained
        #    and this makes it not suitable to effectively embed text,
        #    "but it does not know this and embeds anyway".` - cit. Nicola Corbellini
        return EmbedderDumbConfig.get_embedder_from_config({})

    def load_memory(self):
        """Load LongTerMemory and WorkingMemory."""
        # Memory

        # Get embedder size (langchain classes do not store it)
        embedder_size = len(self.embedder.embed_query("hello world"))

        # Get embedder name (useful for for vectorstore aliases)
        if hasattr(self.embedder, "model"):
            embedder_name = self.embedder.model
        elif hasattr(self.embedder, "repo_id"):
            embedder_name = self.embedder.repo_id
        else:
            embedder_name = "default_embedder"

        # instantiate long term memory
        vector_memory_config = {
            "embedder_name": embedder_name,
            "embedder_size": embedder_size,
        }
        return LongTermMemory(vector_memory_config=vector_memory_config)

    def embed_procedures(self):
        def get_key_embedded_procedures_hashes(ep):
            # log.warning(ep)
            metadata = ep.payload["metadata"]
            content = ep.payload["page_content"]
            source = metadata["source"]
            # there may be legacy points with no trigger_type
            trigger_type = metadata.get("trigger_type", "unsupported")
            return f"{source}.{trigger_type}.{content}"

        def get_key_active_procedures_hashes(ap, trigger_type, trigger_content):
            return f"{ap.name}.{trigger_type}.{trigger_content}"

        # Retrieve from vectorDB all procedural embeddings
        embedded_procedures = self.memory.vectors.procedural.get_all_points()
        embedded_procedures_hashes = {get_key_embedded_procedures_hashes(ep): ep.id for ep in embedded_procedures}

        # Easy access to active procedures in mad_hatter (source of truth!)
        active_procedures_hashes = {get_key_active_procedures_hashes(ap, trigger_type, trigger_content): {
            "obj": ap,
            "source": ap.name,
            "type": ap.procedure_type,
            "trigger_type": trigger_type,
            "content": trigger_content,
        } for ap in self.mad_hatter.procedures for trigger_type, trigger_list in ap.triggers_map.items() for trigger_content in trigger_list}

        # points_to_be_kept = set(active_procedures_hashes.keys()) and set(embedded_procedures_hashes.keys()) not necessary
        points_to_be_deleted = set(embedded_procedures_hashes.keys()) - set(
            active_procedures_hashes.keys()
        )
        points_to_be_embedded = set(active_procedures_hashes.keys()) - set(
            embedded_procedures_hashes.keys()
        )

        if points_to_be_deleted_ids := [embedded_procedures_hashes[p] for p in points_to_be_deleted]:
            log.warning(f"Deleting triggers: {points_to_be_deleted}")
            self.memory.vectors.procedural.delete_points(points_to_be_deleted_ids)

        active_triggers_to_be_embedded = [active_procedures_hashes[p] for p in points_to_be_embedded]
        for t in active_triggers_to_be_embedded:
            trigger_embedding = self.embedder.embed_documents([t["content"]])
            self.memory.vectors.procedural.add_point(
                t["content"],
                trigger_embedding[0],
                {
                    "source": t["source"],
                    "type": t["type"],
                    "trigger_type": t["trigger_type"],
                    "when": time.time(),
                },
            )

            log.warning(
                f"Newly embedded {t['type']} trigger: {t['source']}, {t['trigger_type']}, {t['content']}"
            )

    def send_ws_message(self, content: str, msg_type: MSG_TYPES = "notification"):
        """Send a message via websocket.

        This method is useful for sending a message via websocket directly without passing through the LLM

        Parameters
        ----------
        content : str
            The content of the message.
        msg_type : str
            The type of the message. Should be either `notification`, `chat`, `chat_token` or `error`
        """

        if self.ws is None:
            log.warning(f"No websocket connection is open for user {self.user_id}")
            return

        options = get_args(MSG_TYPES)

        if msg_type not in options:
            raise ValueError(
                f"The message type `{msg_type}` is not valid. Valid types: {', '.join(options)}"
            )

        if msg_type == "error":
            self.__send_ws_json(
                {"type": msg_type, "name": "GenericError", "description": str(content)}
            )
        else:
            self.__send_ws_json({"type": msg_type, "content": content})

    def send_chat_message(self, message: Union[str, CatMessage], save=False):
        if self.ws is None:
            log.warning(f"No websocket connection is open for user {self.user_id}")
            return

        if isinstance(message, str):
            why = self.__build_why()
            message = CatMessage(content=message, user_id=self.user_id, why=why)

        if save:
            self.working_memory.update_conversation_history(
                who="AI", message=message["content"], why=message.why
            )

        self.__send_ws_json(message.model_dump())

    def send_notification(self, content: str):
        self.send_ws_message(content=content, msg_type="notification")

    def send_error(self, error: Union[str, Exception]):
        if self.ws is None:
            log.warning(f"No websocket connection is open for user {self.user_id}")
            return

        if isinstance(error, str):
            error_message = {
                "type": "error",
                "name": "GenericError",
                "description": str(error),
            }
        else:
            error_message = {
                "type": "error",
                "name": error.__class__.__name__,
                "description": str(error),
            }

        self.__send_ws_json(error_message)

    def recall_relevant_memories_to_working_memory(self, query=None):
        """Retrieve context from memory.

        The method retrieves the relevant memories from the vector collections that are given as context to the LLM.
        Recalled memories are stored in the working memory.

        Parameters
        ----------
        query : str, optional
        The query used to make a similarity search in the Cat's vector memories. If not provided, the query
        will be derived from the user's message.

        Notes
        -----
        The user's message is used as a query to make a similarity search in the Cat's vector memories.
        Five hooks allow to customize the recall pipeline before and after it is done.

        See Also
        --------
        cat_recall_query
        before_cat_recalls_memories
        before_cat_recalls_episodic_memories
        before_cat_recalls_declarative_memories
        before_cat_recalls_procedural_memories
        after_cat_recalls_memories
        """
        recall_query = query

        if query is None:
            # If query is not provided, use the user's message as the query
            recall_query = self.working_memory.user_message_json.text

        # We may want to search in memory
        recall_query = self.mad_hatter.execute_hook(
            "cat_recall_query", recall_query, cat=self
        )
        log.info(f"Recall query: '{recall_query}'")

        # Embed recall query
        recall_query_embedding = self.embedder.embed_query(recall_query)
        self.working_memory.recall_query = recall_query
        
        # keep track of embedder model usage
        self.working_memory.model_interactions.append(
            EmbedderModelInteraction(
                prompt=recall_query,
                reply=recall_query_embedding,
                input_tokens=len(tiktoken.get_encoding("cl100k_base").encode(recall_query)),
            )
        )

        # hook to do something before recall begins
        self.mad_hatter.execute_hook("before_cat_recalls_memories", cat=self)

        # Setting default recall configs for each memory
        # TODO: can these data structures become instances of a RecallSettings class?
        default_episodic_recall_config = {
            "embedding": recall_query_embedding,
            "k": 3,
            "threshold": 0.7,
            "metadata": {"source": self.user_id},
        }

        default_declarative_recall_config = {
            "embedding": recall_query_embedding,
            "k": 3,
            "threshold": 0.7,
            "metadata": None,
        }

        default_procedural_recall_config = {
            "embedding": recall_query_embedding,
            "k": 3,
            "threshold": 0.7,
            "metadata": None,
        }

        # hooks to change recall configs for each memory
        recall_configs = [
            self.mad_hatter.execute_hook(
                "before_cat_recalls_episodic_memories",
                default_episodic_recall_config,
                cat=self,
            ),
            self.mad_hatter.execute_hook(
                "before_cat_recalls_declarative_memories",
                default_declarative_recall_config,
                cat=self,
            ),
            self.mad_hatter.execute_hook(
                "before_cat_recalls_procedural_memories",
                default_procedural_recall_config,
                cat=self,
            ),
        ]

        memory_types = self.memory.vectors.collections.keys()

        for config, memory_type in zip(recall_configs, memory_types):
            memory_key = f"{memory_type}_memories"

            # recall relevant memories for collection
            vector_memory = getattr(self.memory.vectors, memory_type)
            memories = vector_memory.recall_memories_from_embedding(**config)

            setattr(
                self.working_memory, memory_key, memories
            )  # self.working_memory.procedural_memories = ...

        # hook to modify/enrich retrieved memories
        self.mad_hatter.execute_hook("after_cat_recalls_memories", cat=self)

    def llm(self, prompt: str, stream: bool = False) -> str:
        """Generate a response using the LLM model.

        This method is useful for generating a response with both a chat and a completion model using the same syntax

        Parameters
        ----------
        prompt : str
            The prompt for generating the response.

        Returns
        -------
        str
            The generated response.

        """

        # should we stream the tokens?
        callbacks = []
        if stream:
            callbacks.append(NewTokenHandler(self))

        # Add a token counter to the callbacks
        caller = utils.get_caller_info()
        callbacks.append(ModelInteractionHandler(self, caller or "StrayCat"))

        # here we deal with motherfucking langchain
        prompt = ChatPromptTemplate(
            messages=[
                SystemMessage(content=prompt)
                # TODO: add here optional convo history passed to the method, 
                #  or taken from working memory
            ]
        )

        chain = (
            prompt
            | RunnableLambda(lambda x: utils.langchain_log_prompt(x, f"{caller} prompt"))
            | self.llm
            | RunnableLambda(lambda x: utils.langchain_log_output(x, f"{caller} prompt output"))
            | StrOutputParser()
        )

        output = chain.invoke(
            {}, # in case we need to pass info to the template
            config=RunnableConfig(callbacks=callbacks)
        )

        return output


    async def __call__(self, message_dict):
        """Call the Cat instance.

        This method is called on the user's message received from the client.

        Parameters
        ----------
        message_dict : dict
            Dictionary received from the Websocket client.

        Returns
        -------
        final_output : dict
            Dictionary with the Cat's answer to be sent to the client.

        Notes
        -----
        Here happens the main pipeline of the Cat. Namely, the Cat receives the user's input and recall the memories.
        The retrieved context is formatted properly and given in input to the Agent that uses the LLM to produce the
        answer. This is formatted in a dictionary to be sent as a JSON via Websocket to the client.

        """

        # Parse websocket message into UserMessage obj
        user_message = UserMessage.model_validate(message_dict)
        log.info(user_message)

        # set a few easy access variables
        self.working_memory.user_message_json = user_message

        # keeping track of model interactions
        self.working_memory.model_interactions = []

        # hook to modify/enrich user input
        self.working_memory.user_message_json = self.mad_hatter.execute_hook(
            "before_cat_reads_message", self.working_memory.user_message_json, cat=self
        )

        # text of latest Human message
        user_message_text = self.working_memory.user_message_json.text

        # update conversation history (Human turn)
        self.working_memory.update_conversation_history(
            who="Human", message=user_message_text
        )

        # recall episodic and declarative memories from vector collections
        #   and store them in working_memory
        try:
            self.recall_relevant_memories_to_working_memory()
        except Exception as e:
            log.error(e)
            traceback.print_exc()

            err_message = (
                "You probably changed Embedder and old vector memory is not compatible. "
                "Please delete `core/long_term_memory` folder."
            )

            return {
                "type": "error",
                "name": "VectorMemoryError",
                "description": err_message,
            }

        # reply with agent
        try:
            agent_output: AgentOutput = await self.main_agent.execute(self)
        except Exception as e:
            # This error happens when the LLM
            #   does not respect prompt instructions.
            # We grab the LLM output here anyway, so small and
            #   non instruction-fine-tuned models can still be used.
            error_description = str(e)

            log.error(error_description)
            if "Could not parse LLM output: `" not in error_description:
                raise e

            unparsable_llm_output = error_description.replace(
                "Could not parse LLM output: `", ""
            ).replace("`", "")
            agent_output = AgentOutput(
                output=unparsable_llm_output,
            )

        log.info("Agent output returned to stray:")
        log.info(agent_output)

        doc = Document(
            page_content=user_message_text,
            metadata={"source": self.user_id, "when": time.time()},
        )
        doc = self.mad_hatter.execute_hook(
            "before_cat_stores_episodic_memory", doc, cat=self
        )
        # store user message in episodic memory
        # TODO: vectorize and store also conversation chunks
        #   (not raw dialog, but summarization)
        user_message_embedding = self.embedder.embed_documents([user_message_text])
        _ = self.memory.vectors.episodic.add_point(
            doc.page_content,
            user_message_embedding[0],
            doc.metadata,
        )

        # why this response?
        why = self.__build_why()
        # TODO: should these assignations be included in self.__build_why ?
        why.intermediate_steps = agent_output.intermediate_steps
        why.agent_output = agent_output.model_dump()

        # prepare final cat message
        final_output = CatMessage(
            user_id=self.user_id, content=str(agent_output.output), why=why
        )

        # run message through plugins
        final_output = self.mad_hatter.execute_hook(
            "before_cat_sends_message", final_output, cat=self
        )

        # update conversation history (AI turn)
        self.working_memory.update_conversation_history(
            who="AI", message=final_output.content, why=final_output.why
        )

        self.__last_message_time = time.time()

        return final_output

    def run(self, user_message_json):
        try:
            cat_message = self.loop.run_until_complete(self.__call__(user_message_json))
            # send message back to client
            self.send_chat_message(cat_message)
        except Exception as e:
            # Log any unexpected errors
            log.error(e)
            traceback.print_exc()
            # Send error as websocket message
            self.send_error(e)

    def classify(self, sentence: str, labels: List[str] | Dict[str, List[str]]) -> str | None:
        """Classify a sentence.

        Parameters
        ----------
        sentence : str
            Sentence to be classified.
        labels : List[str] or Dict[str, List[str]]
            Possible output categories and optional examples.

        Returns
        -------
        label : str
            Sentence category.

        Examples
        -------
        >>> cat.classify("I feel good", labels=["positive", "negative"])
        "positive"

        Or giving examples for each category:

        >>> example_labels = {
        ...     "positive": ["I feel nice", "happy today"],
        ...     "negative": ["I feel bad", "not my best day"],
        ... }
        ... cat.classify("it is a bad day", labels=example_labels)
        "negative"

        """

        if isinstance(labels, dict):
            labels_names = labels.keys()
            examples_list = "\n\nExamples:"
            for label, examples in labels.items():
                for ex in examples:
                    examples_list += f'\n"{ex}" -> "{label}"'
        else:
            labels_names = labels
            examples_list = ""

        labels_list = '"' + '", "'.join(labels_names) + '"'

        prompt = f"""Classify this sentence:
"{sentence}"

Allowed classes are:
{labels_list}{examples_list}

"{sentence}" -> """

        response = self.llm(prompt)
        log.info(response)

        # find the closest match and its score with levenshtein distance
        best_label, score = min(
            ((label, utils.levenshtein_distance(response, label)) for label in labels_names),
            key=lambda x: x[1],
        )

        # set 0.5 as threshold - let's see if it works properly
        return best_label if score < 0.5 else None

    def stringify_chat_history(self, latest_n: int = 5) -> str:
        """Serialize chat history.
        Converts to text the recent conversation turns.

        Parameters
        ----------
        latest_n : int
            Hoe many latest turns to stringify.

        Returns
        -------
        history : str
            String with recent conversation turns.

        Notes
        -----
        Such context is placed in the `agent_prompt_suffix` in the place held by {chat_history}.

        The chat history is a dictionary with keys::
            'who': the name of who said the utterance;
            'message': the utterance.

        """

        history = self.working_memory.history[-latest_n:]

        history_string = ""
        for turn in history:
            history_string += f"\n - {turn['who']}: {turn['message']}"

        return history_string

    def langchainfy_chat_history(self, latest_n: int = 5) -> List[BaseMessage]:
        chat_history = self.working_memory.history[-latest_n:]

        langchain_chat_history = []
        for message in chat_history:
            if message["role"] == Role.Human:
                langchain_chat_history.append(
                    HumanMessage(name=message["who"], content=message["message"])
                )
            else:
                langchain_chat_history.append(
                    AIMessage(name=message["who"], content=message["message"])
                )

        return langchain_chat_history

    @property
    def user_id(self) -> str:
        return self.__user.id

    @property
    def rabbit_hole(self) -> RabbitHole:
        return CheshireCat().rabbit_hole

    @property
    def mad_hatter(self) -> MadHatter:
        return CheshireCat().mad_hatter

    @property
    def white_rabbit(self) -> WhiteRabbit:
        return CheshireCat().white_rabbit

    @property
    def loop(self) -> AbstractEventLoop:
        return self.__loop

    @property
    def is_idle(self) -> bool:
        if not self.__last_message_time:
            return False

        return time.time() - self.__last_message_time >= float(get_env("CCAT_STRAYCAT_TIMEOUT"))
