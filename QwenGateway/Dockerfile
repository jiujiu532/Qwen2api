# Stage 1: Build Go Gateway binary
FROM golang:1.22-alpine AS go-builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/gateway ./cmd/main.go

# Stage 2: Minimal runtime image
FROM alpine:3.19
RUN apk add --no-cache ca-certificates tzdata

COPY --from=go-builder /bin/gateway /usr/local/bin/gateway

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/gateway"]
