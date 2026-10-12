"""The Phase-2 agentic assistant: a router, four sub-agents, and one writer.

The whole layer sits on top of the service layer, never on top of the HTTP API.
That is what makes "the agent surface is not a softer door" true: a sub-agent
calls ``generate_forecast`` exactly as the route handler does, so a series under
the minimum refuses for the chatbot too.
"""
