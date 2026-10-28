"""Assembles the agent graph: 11 nodes, the routing table, and checkpointing."""

from dataclasses import dataclass

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings
from app.llm import DetailExtractor, IntentRouter, OllamaExtractor, OllamaRouter
from app.moderation import RulesModerator
from app.nodes.clarify_node import ClarifyNode
from app.nodes.confirmation_node import ConfirmationNode
from app.nodes.handoff_node import HandoffNode
from app.nodes.identity_node import IdentityNode
from app.nodes.moderation_node import ModerationNode
from app.nodes.planner_node import ActionPlannerNode
from app.nodes.policy_answer_node import PolicyAnswerNode
from app.nodes.response_node import ResponseNode
from app.nodes.router_node import RouterNode
from app.nodes.step_up_node import StepUpNode
from app.nodes.tool_node import ToolNode
from app.routing import Routes
from app.state import ConversationState
from app.toolbox import McpToolbox, Toolbox, ToolboxFactory


@dataclass
class AgentNodes:
    moderation: ModerationNode
    router: RouterNode
    clarify: ClarifyNode
    policy_answer: PolicyAnswerNode
    identity: IdentityNode
    planner: ActionPlannerNode
    step_up: StepUpNode
    confirmation: ConfirmationNode
    tool: ToolNode
    respond: ResponseNode
    handoff: HandoffNode


class GraphBuilder:
    """Turns the nodes and the routing table into a compiled LangGraph graph."""

    def __init__(
        self, nodes: AgentNodes, routes: Routes, checkpointer: BaseCheckpointSaver
    ) -> None:
        self.nodes = nodes
        self.routes = routes
        self.checkpointer = checkpointer

    def build(self) -> CompiledStateGraph:
        n, r = self.nodes, self.routes
        graph = StateGraph(ConversationState)
        graph.add_node("moderate", n.moderation.run)
        graph.add_node("route", n.router.run)
        graph.add_node("clarify", n.clarify.run)
        graph.add_node("policy_answer", n.policy_answer.run)
        graph.add_node("verify", n.identity.run)
        graph.add_node("plan", n.planner.run)
        graph.add_node("step_up", n.step_up.run)
        graph.add_node("confirm", n.confirmation.run)
        graph.add_node("execute", n.tool.run)
        graph.add_node("respond", n.respond.run)
        graph.add_node("handoff", n.handoff.run)

        graph.add_edge(START, "moderate")
        graph.add_conditional_edges("moderate", r.after_moderation, ["route", "respond"])
        graph.add_conditional_edges(
            "route",
            r.after_route,
            ["handoff", "clarify", "policy_answer", "respond", "plan", "verify"],
        )
        graph.add_conditional_edges("clarify", r.after_clarify, ["handoff", "respond"])
        graph.add_edge("policy_answer", "respond")
        graph.add_conditional_edges(
            "verify", r.after_verify, ["handoff", "plan", "respond", "verify"]
        )
        graph.add_conditional_edges(
            "plan", r.after_plan, ["handoff", "respond", "execute", "step_up", "confirm"]
        )
        graph.add_conditional_edges("step_up", r.after_step_up, ["confirm", "respond", "step_up"])
        graph.add_conditional_edges("confirm", r.after_confirm, ["execute", "respond"])
        graph.add_conditional_edges("execute", r.after_execute, ["handoff", "respond"])
        graph.add_edge("respond", END)
        graph.add_edge("handoff", END)
        return graph.compile(checkpointer=self.checkpointer)


def build_graph(
    config: Settings,
    *,
    router: IntentRouter | None = None,
    extractor: DetailExtractor | None = None,
    toolboxes: ToolboxFactory | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """The real graph by default. Tests pass fakes for the models and tools."""

    def mcp_toolbox(session_token: str) -> Toolbox:
        return McpToolbox(config.mcp_url, session_token)

    moderator = RulesModerator()
    tools = toolboxes or mcp_toolbox
    nodes = AgentNodes(
        moderation=ModerationNode(moderator),
        router=RouterNode(
            router or OllamaRouter(config.router_model, config.ollama_base_url),
            config.router_min_confidence,
        ),
        clarify=ClarifyNode(config.max_clarifications),
        policy_answer=PolicyAnswerNode(),
        identity=IdentityNode(config.max_pin_attempts),
        planner=ActionPlannerNode(
            extractor or OllamaExtractor(config.agent_model, config.ollama_base_url),
            tools,
            config.transactions_to_show,
        ),
        step_up=StepUpNode(),
        confirmation=ConfirmationNode(moderator),
        tool=ToolNode(tools),
        respond=ResponseNode(),
        handoff=HandoffNode(),
    )
    routes = Routes(config.router_min_confidence)
    return GraphBuilder(nodes, routes, checkpointer or InMemorySaver()).build()
