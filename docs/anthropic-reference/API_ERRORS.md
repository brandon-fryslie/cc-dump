Using the API

The API follows a predictable HTTP error code format:

-   400 - `invalid_request_error`: There was an issue with the format or content of your request. This error type may also be used for other 4XX status codes not listed below.

-   401 - `authentication_error`: There's an issue with your API key.

-   403 - `permission_error`: Your API key does not have permission to use the specified resource.

-   404 - `not_found_error`: The requested resource was not found.

-   413 - `request_too_large`: Request exceeds the maximum allowed number of bytes. The maximum request size is 32 MB for standard API endpoints.

-   429 - `rate_limit_error`: Your account has hit a rate limit.

-   500 - `api_error`: An unexpected error has occurred internal to Anthropic's systems.

-   529 - `overloaded_error`: The API is temporarily overloaded.

    529 errors can occur when APIs experience high traffic across all users.

    In rare cases, if your organization has a sharp increase in usage, you might see 429 errors due to acceleration limits on the API. To avoid hitting acceleration limits, ramp up your traffic gradually and maintain consistent usage patterns.


When receiving a [streaming](./STREAMING.md) response via SSE, it's possible that an error can occur after returning a 200 response, in which case error handling wouldn't follow these standard mechanisms.

Errors are always returned as JSON, with a top-level `error` object that always includes a `type` and `message` value. The response also includes a `request_id` field for easier tracking and debugging. For example:
