# septic-canary
Web service abstracting over the HouseCanary API. Checks if a given address has a septic system.

## Project layout
The project is small.
* The root directory contains build configs and documentation
* All main code is located within `septic_canary/main.py`
* All test code is located within `tests/test_main.py`

### Running the project
To run the project, you can build and run the provided `Dockerfile`:

```shell
# Build the image locally
docker build -t septic-canary-test .
# Run the image, injecting your HouseCanary credentials into the environment
docker run --rm \
  -p 8000:80 \
  -e HOUSE_CANARY_API_KEY="${your-api-key}" \
  -e HOUSE_CANARY_API_SECRET="${your-api-secret}" \
  -e API_USERNAME="${username-for-api}" \
  -e API_PASSWORD="${password-for-api}" \
  septic-canary-test
# Navigate to http://localhost:8000/docs in your browser to interact with the API via OpenAPI.
# Use the configured API_USERNAME and API_PASSWORD to authenticate.
```

If you'd rather not use `docker`, you can alternatively run the project directly using `poetry`.
Install `poetry` using [these directions](https://python-poetry.org/docs/master/#installation), then run:
```shell
HOUSE_CANARY_API_KEY="${your-api-key}" HOUSE_CANARY_API_SECRET="${your-api-secret}" API_USERNAME="${username-for-api}" API_PASSWORD="${password-for-api}" \
  poetry run uvicorn septic_canary.main:app
# Navigate to http://localhost:8000/docs in your browser to interact with the API via OpenAPI.
# Use the configured API_USERNAME and API_PASSWORD to authenticate.
```

### Configuring the project
Instead of passing your HouseCanary credentials over the CLI, you can write them to file. If you're running the app in
Docker, first write the configuration to your host:
```shell
cat <<EOF > canary.env
HOUSE_CANARY_API_KEY="${your-api-key}"
HOUSE_CANARY_API_SECRET="${your-api-secret}"
EOF
```
Then mount it into the container when running:
```shell
docker run --rm \
  -p 8000:80 \
  -v ./canary.conf:/app/.env \
  septic-canary-test
```

If running via `poetry`, write your config into `.env` in the project root.

### Testing the project
Run unit tests via `poetry`:
```shell
poetry run pytest
```

## Project design

### Dependencies
The project gets away with being very minimal because it builds on top of some powerful dependencies:

* [fastapi](https://fastapi.tiangolo.com/) is used for the web framework. I chose it because (in my experience)
  it handles nearly all the "boring" boilerplate needed to create a web service, while still allowing flexible
  project layouts and straightforward dependency injection during tests.
* [uvicorn](https://www.uvicorn.org/) is used to actually run the FastAPI app. It's recommended in all the FastAPI
  doc examples and I didn't see a need to spend time investigating alternatives.
* [pydantic](https://pydantic-docs.helpmanual.io/) is used to model API models and conifg settings. Apart from
  being a building block of FastAPI, I like it because it handles nearly all the boilerplate needed to define
  "data class"-style models in Python, with tight type-hint integration. If this project continued to grow in
  complexity, I'd expect the structure of Pydantic models to become progressively more useful.
* [requests](https://docs.python-requests.org/en/master/index.html) is used to query the HouseCanary API. There
  are probably other HTTP client libraries out there for Python, but I've never felt the need to investigate because
  `requests` Just Works.

Testing via `pytest` also turned out to be straightforward thanks to [`requests-mock`](https://requests-mock.readthedocs.io/en/latest/),
which handles injection a mock transport-adapter into `requests` during unit tests.

### API design
The service exposes a single API, `GET /api/v1/property/details`. Its request and response structure is mainly aimed at
translating HouseCanary's unique `GET /v2/property/details` API into a more standardized form, targeted at our use-case
of checking septic systems.
* The API is versioned (starting at `v1`) to allow for future redesigns.
* The API is protected via Basic authentication. A single username/password combo is permitted; all others are rejected.
* Request parameters include `street`, `unit`, `city`, `state`, and `zip`. They are passed as URL params.
  * I used `street` instead of `address` (the HouseCanary equivalent) to be more specific.
  * I used `zip` instead of `zipcode` (the HouseCanary equivalent) because as a user of APIs, I've found myself annoyed
    when I'm typing out a `curl` command and request parameters are longer than I feel they need to be.
* Successful responses come back as JSON objects with a single boolean `has_septic_system` field.
  * The expectation is that if consumers of the service ever wanted to know more details about the queried properties,
    more fields would be added to the response object.
  * If consumers wanted to know about different types of sewer systems, `has_septic_system` could be deprecated and
    a new `sewer_system_type` enum could be added to the response.
* A variety of error responses are possible.
  * `401`: Returned if the request is missing Basic auth / if it provides incorrect credentials.
  * `422`: Returned if the client doesn't provide enough parameters to attempt address resolution.
  * `429`: Returned if HouseCanary returns a `429` (too many requests) code, because the end client is the one that
    ultimately needs to be rate-limited. Includes a [`Retry-After`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Retry-After)
    header to help clients.
  * `404`: Returned if HouseCanary fails to resolve the requested address.
  * `500`: Returned if HouseCanary returns any other error code (`400` or `401` according to their API docs), because
    any other potential error means our service has a bug.

## Things I'd do differently in a "real" project

### API design
I chose to change some of the parameter names from the HomeCanary API when designing this middleware. In a real
project I would have consulted with teammates and potential users before making that choice, in case my opinions
about "better" names don't match how others want to use the service.

For simplicity, I chose to protect the service via Basic auth, with only 1 valid username/password combo passed in
at runtime via configuration. In a real project that setup might be viable at the very beginning of the project, but
I'd expect it to eventually get replaced by something more sophisticated like OAuth.

### Project layout
To keep things simple, I wrote all of this project's code in one file, and most of it in a single function within
that file. In a real project that sort of pattern would quickly become un-maintainable as the project grew. To avoid
problems, I'd first want to split up the logic into helper functions, then split up the function definitions across
multiple files / modules. FastAPI isn't opinionated about project layout so I'd need to consult with teammates about
a directory structure that made sense for the service.

### Testing
The unit tests in this project mock out all HTTP requests to HouseCanary, returning fake response payloads based on
my interpretation of their API docs. Ideally I could have manually run a few test queries against the HouseCanary API
to verify that my understanding of the response schemas was correct, but I wasn't able to find a way to sign up for a
test / free account on their website without contacting their sales team. In a real project I would have pushed
through that process to get a real API key/secret pair for use in manual testing.

I also would have wanted to set up some integration/e2e tests to fully cover the HTTP layer of the app (vs. the unit
tests, which bypass the request-parsing layer to exercise the business logic directly).  Depending on the rate-limits
imposed by HouseCanary on the use of their sandbox / test API calls, those tests would be set up either to query
HouseCanary directly or to query a minimal "fake" HouseCanary server that we'd need to write as another web service.

### Continuous integration
In a real project I'd set up a CI pipeline to validate pull requests. In addition to running unit and integration tests,
I'd want the pipeline to check linting rules to ensure the project adhered to the team's chosen style standards. The
Python ecosystem has a handful of solid linters (i.e. `black`, `mypy`) that I'd consider using for this step.

### Developer experience
The commands used to build & test the project are non-trivial, and probably not something we'd want the team to have
to remember. While the commands are currently documented in this `README.md`, we could improve the developer experience
by moving them into shell scripts / a `Makefile` that the team could call as short-hand. This sort of infrastructure
would become progressively more useful as we added more types of builds/tests/linting.
