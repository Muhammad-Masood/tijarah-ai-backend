import asyncio
from typing import Optional, Dict
from pydantic import BaseModel
from contextlib import AsyncExitStack
import os
from mcp import ClientSession, Tool
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv
from google import genai
import json

load_dotenv()  # load environment variables from .env

class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        # self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        # self.open_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.open_ai = OpenAI(
            # base_url="https://openrouter.ai/api/v1",
            base_url="https://api.groq.com/openai/v1",
            # base_url="https://generativelanguage.googleapis.com/v1beta/",
            # base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            # base_url="https://openrouter.ai/api/v1/chat/completions",
            # api_key=os.getenv("OPEN_ROUTER_AI_API_KEY")
            # api_key=os.getenv("GEMINI_API_KEY")
            api_key=os.getenv("GROQ_API_KEY")
        )
        self.sse_urls = []
        self.tools = []
        self.tools_context = {}
        
    # methods will go here

    def _add_sse_urls(self, sse_urls:list[str]):
        self.sse_urls.extend(sse_urls)
    
    def _get_sse_urls(self):
        return self.sse_urls
    
    async def get_session(self):
        url = self._get_sse_urls()[0]
        async with sse_client(url) as (in_stream, out_stream):
            async with ClientSession(in_stream, out_stream) as session:
                await session.initialize()
                yield session
        
    async def get_tools(self, session: ClientSession) -> list[Tool] | None:
        """Get access to all tools of an MCP server
        Args:
            url: Streaming url of the mcp server
        """
        try:
            tools = (await session.list_tools()).tools
            return tools
        except Exception as e:
            print(f"Error getting tools: {str(e)}")
            return None
    
    async def process_query(self, query: str, session: ClientSession) -> str:
        """Process a query with LLM and available tools"""
        
        messages = [
            {
                "role": "system",
                "content": """You are a helpful customer support agent, after callimg any tool, the `tool` role will be appended like this in your `messages` context: 
                {'role': 'tool', 'tool_call_id': 'tool_call_id', 'content': "type='' text='<tool_call_output_content>' annotations=None"} 
                After getting this `tool` role, you can analyze the `content` of the `tool` and then answer the related query with the help of this `tool` content."""
            },
            {
                "role": "user",
                "content": query
            }
        ]
        # sse_urls = self._get_sse_urls()
        tools = await self.get_tools(session)

        available_tools = [{
            "type": "function",
            "function":{
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
            # "input_schema": tool.inputSchema
        } for tool in tools]

        print("Available tools context: ", available_tools)

        response = self.open_ai.chat.completions.create(
            # model="meta-llama/llama-3.3-70b-instruct:free",
            # model="gemini-2.0-flash",
            model="deepseek-r1-distill-llama-70b",
            # model="deepseek/deepseek-prover-v2:free",
            messages=messages,
            tools=available_tools,
            tool_choice="auto"
        )
        
        # response = self.open_ai.responses.create(
        #     model="gemini-2.0-flash",
        #     tools=available_tools,
        #     input=messages
        #     # tool_choice="auto"
        # )
        print(response)

        final_text = []
        assistant_message_content = []

        for choice in response.choices:
            if choice.finish_reason == "stop":
                content = choice.message.content
                print("Message content: ", content)
                final_text.append(content)
                assistant_message_content.append(content)
            elif choice.finish_reason == 'tool_calls':
                for tool_call in choice.message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    print(tool_name, "tool_args: ", tool_args, type(tool_args))
                    # Execute tool call
                    result = await session.call_tool(tool_name, arguments=json.loads(tool_args))
                    final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")
                    choice = choice.model_dump()
                    choice_tool_call = choice["message"]["tool_calls"][0]
                    choice_tool_call["function"]["arguments"] = str(json.loads(choice_tool_call["function"]["arguments"]))
                    print("choice", choice)
                    assistant_message_content.append(choice)
                    print("\n result", result, "\n assistant message content: ", assistant_message_content)
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": choice["message"]["tool_calls"]
                    })
                    # messages.append(choice["message"])
                    print("\n result content dict: ", result.content[0].model_dump())
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        # "tool_use_name": tool_name,
                        "content": str(result.content[0])
                    })
                    # messages.append({
                    #     "role": "user",
                    #     "content": [
                    #         {
                    #             "type": "tool_result",
                    #             # "tool_use_id": content.id,
                    #             "tool_use_name": tool_name,
                    #             "content": result.content[0].model_dump()
                    #         }
                    #     ]
                    # })
                    print("\n Messages: ", messages)
                    response_with_tool_call = self.open_ai.chat.completions.create(
                        # model="gemini-2.0-flash",
                        model="deepseek-r1-distill-llama-70b",
                        messages=messages,
                        tools=available_tools,
                        tool_choice="auto"
                        )
                    # 4042a36a-0753-4de8-85a8-514edc92351d
                    print("\n Second call to llm response: ",response_with_tool_call)
                    
                    final_text.append(response_with_tool_call.choices[0].message.content)
                    # print("Response output text: ", response.output_text)
                    # final_text.append(response.output_text)
                
        return " \n ".join(final_text)

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()
