"""Safe placeholder command; starts no service and performs no inference."""


def main() -> None:
    print("InferLab worker: not configured. No jobs were claimed or executed.")


if __name__ == "__main__":
    main()
